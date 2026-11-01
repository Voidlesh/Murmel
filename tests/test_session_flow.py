import asyncio
import json

import numpy as np
import pytest

from engine import config, server
from engine.audio import SAMPLE_RATE


def tone(seconds: float) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return (0.2 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)


class FakeRecorder:
    def __init__(self) -> None:
        self.active = False
        self.pending = np.zeros(0, dtype=np.float32)

    def start(self, device=None) -> None:
        self.active = True

    def drain(self) -> np.ndarray:
        out, self.pending = self.pending, np.zeros(0, dtype=np.float32)
        return out

    def stop(self) -> np.ndarray:
        self.active = False
        return self.drain()


class FakeTranscriber:
    model_name = "fake"
    device = "cpu"

    def transcribe(self, audio, language, beam_size, vocabulary):
        from engine.stt import SttResult

        return SttResult(f"abschnitt {audio.size}", "de", 1)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    eng = server.Engine()
    account = eng.accounts.register("Ann", "ann@example.de", "geheim123")
    eng._activate(account)
    eng.settings = {**eng.settings, "session_keep_audio": False}
    eng.recorder = FakeRecorder()
    eng.transcriber = FakeTranscriber()
    eng.state = "idle"
    return eng


def test_session_writes_one_segment_per_pause_and_the_rest_on_stop(engine):
    async def scenario():
        session = await engine.api_session_start("Standup")
        engine.recorder.pending = np.concatenate([tone(6), silence(1.0), tone(3)])
        await asyncio.sleep(server.SESSION_TICK_S * 2)
        finished = await engine.api_session_stop()
        return session, finished

    session, finished = asyncio.run(scenario())

    assert session["status"] == "recording"
    assert finished["status"] == "done"
    segments = engine.store.session_segments(session["id"])
    assert len(segments) == 2
    assert segments[0]["start_s"] == 0.0
    assert segments[1]["start_s"] == pytest.approx(segments[0]["end_s"])
    assert engine.session_id is None


def test_dictation_is_blocked_while_a_session_runs(engine):
    async def scenario():
        await engine.api_session_start()
        await engine.start_recording()
        return engine.recorder.active

    assert asyncio.run(scenario()) is True  # the session recorder stays the only active one


def test_second_session_is_rejected(engine):
    async def scenario():
        await engine.api_session_start()
        with pytest.raises(ValueError):
            await engine.api_session_start()
        await engine.api_session_stop()

    asyncio.run(scenario())


def test_stop_without_session_fails(engine):
    with pytest.raises(ValueError):
        asyncio.run(engine.api_session_stop())


def test_summary_requires_llm(engine):
    session = engine.store.create_session("", started_at=1.0, language="de")
    with pytest.raises(ValueError):
        asyncio.run(engine.api_session_summarize(session["id"]))


def test_account_change_is_refused_during_session_and_recording_continues(engine):
    async def scenario():
        await engine.api_session_start()
        with pytest.raises(ValueError):
            await engine.api_auth_logout()
        still_running = engine.session_id is not None and engine.recorder.active
        await engine.api_session_stop()
        return still_running

    assert asyncio.run(scenario()) is True


def test_running_session_cannot_be_summarized(engine):
    async def scenario():
        session = await engine.api_session_start()
        with pytest.raises(ValueError):
            await engine.api_session_summarize(session["id"])
        await engine.api_session_stop()

    asyncio.run(scenario())


def test_failed_microphone_start_leaves_no_running_session(engine):
    def broken_start(device=None):
        raise OSError("Gerät belegt")

    engine.recorder.start = broken_start

    async def scenario():
        with pytest.raises(ValueError, match="Gerät belegt"):
            await engine.api_session_start()

    asyncio.run(scenario())
    assert engine.session_id is None
    assert engine.store.list_sessions()[0]["status"] == "error"


def test_tiny_tail_is_not_transcribed(engine):
    async def scenario():
        await engine.api_session_start()
        engine.recorder.pending = tone(0.2)
        return await engine.api_session_stop()

    finished = asyncio.run(scenario())
    assert finished["status"] == "done"
    assert engine.store.session_segments(finished["id"]) == []


def test_hotkey_start_without_model_reports_instead_of_raising(engine):
    engine.transcriber = None
    asyncio.run(engine._session_toggle())
    assert engine.session_id is None


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, data: str) -> None:
        self.sent.append(json.loads(data))


def test_json_api_roundtrip_like_the_dashboard(engine):
    async def call(ws, request_id, method, **params):
        await engine._dispatch(ws, json.dumps({"id": request_id, "method": method, "params": params}))
        return ws.sent[-1]

    async def scenario():
        ws = FakeSocket()
        started = await call(ws, 1, "session_start", title="Dashboard-Test")
        engine.recorder.pending = np.concatenate([tone(6), silence(1.0), tone(3)])
        await asyncio.sleep(server.SESSION_TICK_S * 2)
        stopped = await call(ws, 2, "session_stop")
        listed = await call(ws, 3, "session_list")
        detail = await call(ws, 4, "session_get", id=stopped["result"]["id"])
        return started, stopped, listed, detail

    started, stopped, listed, detail = asyncio.run(scenario())
    assert "error" not in started and started["id"] == 1
    assert stopped["result"]["status"] == "done"
    assert listed["result"][0]["title"] == "Dashboard-Test"
    assert len(detail["result"]["segments"]) == 2


def test_session_hotkey_must_differ_from_dictation_hotkey(engine):
    with pytest.raises(ValueError):
        asyncio.run(engine.api_set_settings({"session_hotkey": "caps lock"}))
    assert engine.settings["session_hotkey"] == ""


def test_unknown_session_hotkey_is_not_saved(engine):
    with pytest.raises(ValueError):
        asyncio.run(engine.api_set_settings({"session_hotkey": "keine-taste"}))
    assert engine.settings["session_hotkey"] == ""


def test_valid_session_hotkey_is_saved_and_reconnected(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(engine, "_configure_session_hotkey", lambda: calls.append(True))
    asyncio.run(engine.api_set_settings({"session_hotkey": "ctrl+alt+m"}))
    assert engine.settings["session_hotkey"] == "ctrl+alt+m"
    assert calls == [True]
