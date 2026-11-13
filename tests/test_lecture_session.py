"""Online lecture flow: desktop audio as the main source, robust audio files, re-run, export."""
import asyncio
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from engine import audio, config, export, server
from engine.audio import SAMPLE_RATE


def tone(seconds: float, level: float = 0.2) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return (level * np.sin(2 * np.pi * 200 * t)).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)


class FakeRecorder:
    def __init__(self, name: str = "Fake") -> None:
        self.active = False
        self.pending = np.zeros(0, dtype=np.float32)
        self.device_name = name
        self.level_db = audio.SILENCE_DB
        self.level_at = 0.0
        self.alive = True
        self.restarts = 0
        self.fail_start: Exception | None = None

    def start(self, device=None, loopback=False, fill_gaps=False) -> None:
        if self.fail_start:
            raise self.fail_start
        self.active = True

    def healthy(self) -> bool:
        return self.alive

    def restart(self) -> None:
        self.restarts += 1
        self.alive = True

    def drain(self) -> np.ndarray:
        out, self.pending = self.pending, np.zeros(0, dtype=np.float32)
        return out

    def stop(self) -> np.ndarray:
        self.active = False
        return self.drain()


class FakeTranscriber:
    model_name = "fake"
    device = "cuda"

    def __init__(self) -> None:
        self.vocabularies: list[list[str]] = []

    def transcribe(self, samples, language, beam_size, vocabulary, strict=False):
        from engine.stt import SttResult

        self.vocabularies.append(list(vocabulary))
        return SttResult(f"abschnitt {samples.size}", language or "de", 1)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server.audio, "default_loopback_name", lambda: "Fake")
    eng = server.Engine()
    account = eng.accounts.register("Ann", "ann@example.de", "geheim123")
    eng._activate(account)
    eng.settings = {**eng.settings, "session_keep_audio": True}
    eng.recorder = FakeRecorder("Mikrofon")
    eng._system_recorder = FakeRecorder("Fake")
    eng.transcriber = FakeTranscriber()
    eng.state = "idle"
    return eng


def capture(engine) -> list[dict]:
    sent: list[dict] = []

    async def fake_broadcast(msg):
        sent.append(msg)

    engine.broadcast = fake_broadcast
    return sent


def run_session(engine, feed, ticks: int = 2, **start):
    async def scenario():
        session = await engine.api_session_start(**start)
        feed()
        await asyncio.sleep(server.SESSION_TICK_S * ticks)
        return session, await engine.api_session_stop()

    return asyncio.run(scenario())


def test_desktop_only_session_needs_no_microphone(engine):
    engine.recorder.fail_start = OSError("kein Mikro")

    def feed():
        engine._system_recorder.pending = np.concatenate([tone(6), silence(1.0), tone(3)])

    session, finished = run_session(engine, feed, source="desktop", title="Lineare Algebra")

    assert finished["status"] == "done"
    assert finished["source"] == "desktop"
    segments = engine.store.session_segments(session["id"])
    assert {s["speaker"] for s in segments} == {"them"}
    assert len(segments) == 2


def test_missing_desktop_audio_fails_loudly(engine):
    engine._system_recorder.fail_start = RuntimeError("Keine Wiedergabe gefunden")

    with pytest.raises(ValueError, match="Desktop-Audio konnte nicht starten"):
        asyncio.run(engine.api_session_start(source="desktop"))
    assert engine.session_id is None
    assert engine.store.list_sessions()[0]["status"] == "error"


def test_both_sources_keep_going_without_microphone(engine):
    sent = capture(engine)
    engine.recorder.fail_start = OSError("Gerät belegt")

    session, finished = run_session(engine, lambda: None, source="both")

    assert finished["status"] == "done"
    assert any(m["type"] == "notice" and "Mikrofon nicht verfügbar" in m["text"] for m in sent)


def test_three_audio_files_with_aligned_mix(engine):
    def feed():
        engine._system_recorder.pending = tone(4)
        engine.recorder.pending = tone(3, level=0.1)

    session, finished = run_session(engine, feed, source="both")

    files = {k: Path(v) for k, v in finished["audio"].items()}
    assert set(files) == {"mix", "desktop", "mic"}
    with wave.open(str(files["desktop"])) as w:
        assert w.getnframes() == 4 * SAMPLE_RATE
    with wave.open(str(files["mic"])) as w:
        assert w.getnframes() == 3 * SAMPLE_RATE
    with wave.open(str(files["mix"])) as w:
        assert w.getnframes() == 4 * SAMPLE_RATE  # the longer source decides, the shorter is padded at the end


def test_session_terms_and_language_reach_whisper(engine):
    def feed():
        engine._system_recorder.pending = np.concatenate([tone(6), silence(1.0)])

    session, finished = run_session(engine, feed, source="desktop", language="en", terms="Eigenwert, Jordan-Normalform")

    assert finished["language"] == "en"
    assert finished["terms"] == "Eigenwert, Jordan-Normalform"
    assert engine.transcriber.vocabularies[0][:2] == ["Eigenwert", "Jordan-Normalform"]


def test_dead_stream_is_reconnected_and_noted_in_the_transcript(engine):
    sent = capture(engine)

    async def scenario():
        session = await engine.api_session_start(source="desktop")
        engine._system_recorder.alive = False
        await asyncio.sleep(server.SESSION_TICK_S * 1.5)
        await engine.api_session_stop()
        return session

    session = asyncio.run(scenario())
    assert engine._system_recorder.restarts >= 1
    notes = [s for s in engine.store.session_segments(session["id"]) if s["speaker"] == "system"]
    assert notes and "neu verbunden" in notes[0]["text"]


def test_changed_playback_device_triggers_reconnect(engine, monkeypatch):
    monkeypatch.setattr(server, "DEVICE_CHECK_S", 0.0)
    monkeypatch.setattr(server.audio, "default_loopback_name", lambda: "Kopfhörer")

    async def scenario():
        await engine.api_session_start(source="desktop")
        await asyncio.sleep(server.SESSION_TICK_S * 2.5)  # one tick asks in the background, the next reacts
        await engine.api_session_stop()

    asyncio.run(scenario())
    assert engine._system_recorder.restarts >= 1


def test_silent_desktop_audio_raises_a_warning(engine, monkeypatch):
    monkeypatch.setattr(server, "DESKTOP_SILENT_WARN_S", 0.5)
    sent = capture(engine)

    async def scenario():
        await engine.api_session_start(source="desktop")
        await asyncio.sleep(server.SESSION_TICK_S * 1.5)
        await engine.api_session_stop()

    asyncio.run(scenario())
    warnings = [m for m in sent if m["type"] == "session_warning" and m["kind"] == "desktop_silent"]
    assert warnings and "Fake" in warnings[0]["text"]


def test_levels_are_sent_for_each_source(engine):
    sent = capture(engine)
    engine._system_recorder.level_db = -20.0

    async def scenario():
        await engine.api_session_start(source="both")
        engine._system_recorder.level_at = time.monotonic() + 5  # stays fresh during the test
        await asyncio.sleep(0.4)
        await engine.api_session_stop()

    asyncio.run(scenario())
    levels = [m for m in sent if m["type"] == "session_levels"]
    assert levels and set(levels[-1]["levels"]) == {"you", "them"}
    assert "lag_s" in levels[-1]


def test_retranscribe_replaces_the_transcript_from_the_audio_files(engine):
    def feed():
        engine._system_recorder.pending = np.concatenate([tone(6), silence(1.0), tone(3)])

    session, finished = run_session(engine, feed, source="desktop")
    engine.store.replace_session_segments(session["id"], [("them", 0.0, 1.0, "kaputt")])

    async def rerun():
        await engine.api_session_retranscribe(session["id"])
        await engine._jobs[session["id"]]

    asyncio.run(rerun())
    texts = [s["text"] for s in engine.store.session_segments(session["id"])]
    assert "kaputt" not in texts and len(texts) == 2
    assert engine.store.get_session(session["id"])["status"] == "done"


def test_old_sessions_without_tracks_rerun_their_microphone_file(tmp_path):
    main = tmp_path / "session-1.wav"
    audio.save_wav(tone(1), main)
    assert server._retranscribe_tracks({"audio_path": str(main), "source": ""}) == [("you", main)]
    assert server._retranscribe_tracks({"audio_path": str(main), "source": "import"}) == [("them", main)]


def test_import_turns_a_wav_into_a_session(engine, tmp_path, monkeypatch):
    backup = tmp_path / "obs-aufnahme.wav"
    audio.save_wav(np.concatenate([tone(6), silence(1.0), tone(3)]), backup)
    monkeypatch.setattr(server, "_convert_to_wav", lambda src, dst: (dst.parent.mkdir(parents=True, exist_ok=True), dst.write_bytes(src.read_bytes()), 10.0)[2])

    async def scenario():
        session = await engine.api_session_import(str(backup))
        await engine._jobs[session["id"]]
        return session

    session = asyncio.run(scenario())
    assert session["title"] == "obs-aufnahme"
    assert len(engine.store.session_segments(session["id"])) == 2
    assert engine.store.get_session(session["id"])["status"] == "done"


def test_crash_leaves_a_playable_wav(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, "WAV_SYNC_S", 0.0)
    path = tmp_path / "s.wav"
    writer = audio.WavWriter(path)
    writer.write(tone(2))  # synced right away, then the "crash": the file is never closed
    with wave.open(str(path)) as w:
        assert w.getnframes() == 2 * SAMPLE_RATE


def test_repair_fixes_a_header_that_was_never_updated(tmp_path):
    path = tmp_path / "s.wav"
    path.write_bytes(audio._wav_header(0) + (np.zeros(1600, dtype="<i2")).tobytes())
    assert audio.repair_wav(path) is True
    with wave.open(str(path)) as w:
        assert w.getnframes() == 1600
    assert audio.repair_wav(path) is False


def test_loopback_gaps_are_filled_by_wall_clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(audio.time, "monotonic", lambda: now[0])
    recorder = audio.Recorder(lambda bands: None)
    recorder._fill, recorder._started = True, 100.0
    recorder._callback(np.full((800, 1), 0.1, dtype=np.float32), 800, None, None)
    now[0] = 103.0  # three seconds, nothing played

    out = recorder.drain()

    assert out.size == pytest.approx(3 * SAMPLE_RATE - audio.GAP_KEEP_S * SAMPLE_RATE, abs=1)


def test_resampler_is_continuous_and_removes_high_frequencies():
    rate = 48000
    t = np.arange(rate) / rate
    speech = 0.3 * np.sin(2 * np.pi * 440 * t)
    hiss = 0.3 * np.sin(2 * np.pi * 15000 * t)  # would alias to 1 kHz without a low-pass
    resampler = audio.StreamResampler(rate)
    out = np.concatenate([resampler.process(block) for block in np.split((speech + hiss).astype(np.float32), 20)])

    assert out.size == pytest.approx(SAMPLE_RATE, abs=2)
    spectrum = np.abs(np.fft.rfft(out[1000:-1000]))
    freqs = np.fft.rfftfreq(out[1000:-1000].size, 1 / SAMPLE_RATE)
    alias = spectrum[(freqs > 900) & (freqs < 1100)].max()
    tone_peak = spectrum[(freqs > 400) & (freqs < 480)].max()
    assert alias < tone_peak * 0.05


def test_markdown_export_merges_paragraphs_and_marks_speakers():
    session = {"title": "LA II – VL 5", "started_at": 1_700_000_000, "ended_at": 1_700_000_000 + 3725,
               "source": "both", "terms": "Eigenwert", "notes": "Klausurrelevant: Satz 3.2"}
    segments = [
        {"speaker": "them", "start_s": 0.0, "end_s": 10.0, "text": "Heute geht es um Eigenwerte."},
        {"speaker": "them", "start_s": 11.0, "end_s": 20.0, "text": "Zuerst die Definition."},
        {"speaker": "you", "start_s": 21.0, "end_s": 23.0, "text": "Ist das prüfungsrelevant?"},
        {"speaker": "system", "start_s": 30.0, "end_s": 30.0, "text": "Desktop-Audio neu verbunden"},
        {"speaker": "them", "start_s": 3700.0, "end_s": 3710.0, "text": "Bis nächste Woche."},
    ]
    md = export.to_markdown(session, segments)

    assert md.startswith("# LA II – VL 5\n")
    assert "Dauer 1:02:05" in md
    assert "**Gegenüber** `[00:00]` Heute geht es um Eigenwerte. Zuerst die Definition." in md
    assert "**Du** `[00:21]` Ist das prüfungsrelevant?" in md
    assert "> *[00:30] Desktop-Audio neu verbunden*" in md
    assert "`[1:01:40]`" in md
    assert md.rstrip().endswith("Klausurrelevant: Satz 3.2")


def test_text_export_without_speakers_when_only_one_spoke():
    session = {"title": "VL", "started_at": 0, "ended_at": 60, "notes": ""}
    segments = [
        {"speaker": "them", "start_s": 0.0, "end_s": 5.0, "text": "Erster Satz."},
        {"speaker": "system", "start_s": 6.0, "end_s": 6.0, "text": "Hinweis"},
        {"speaker": "them", "start_s": 6.0, "end_s": 9.0, "text": "Zweiter Satz."},
    ]
    assert export.to_text(session, segments) == "VL\n\nErster Satz. Zweiter Satz.\n"


def test_export_filename_is_safe_for_windows():
    name = export.filename({"title": 'Mathe: "VL" 5/6?', "started_at": 1_700_000_000}, "md")
    assert name.endswith("Mathe VL 56.md")
    assert not set('<>:"/\\|?*') & set(name)


def test_export_api_returns_content_and_filename(engine):
    session = engine.store.create_session("VL 5", started_at=1_700_000_000, language="de", source="desktop")
    engine.store.add_session_segment(session["id"], 0.0, 3.0, "Hallo zusammen.", speaker="them")
    result = asyncio.run(engine.api_session_export(session["id"], "md"))
    assert result["filename"].endswith("VL 5.md")
    assert "Hallo zusammen." in result["content"]
    with pytest.raises(ValueError):
        asyncio.run(engine.api_session_export(session["id"], "pdf"))


def test_rename_rejects_empty_titles(engine):
    session = engine.store.create_session("alt", started_at=1.0, language="de")
    renamed = asyncio.run(engine.api_session_rename(session["id"], "  Neu  "))
    assert renamed["title"] == "Neu"
    with pytest.raises(ValueError):
        asyncio.run(engine.api_session_rename(session["id"], "  "))


def test_failed_summary_does_not_mark_the_session_as_failed(engine, monkeypatch):
    engine.settings = {**engine.settings, "llm": {**engine.settings["llm"], "enabled": True}}
    session = engine.store.create_session("", started_at=1.0, language="de", status="done")

    def boom(text, cfg):
        raise OSError("LM Studio läuft nicht")

    monkeypatch.setattr(server.llm, "summarize_session", boom)
    with pytest.raises(ValueError, match="Zusammenfassung fehlgeschlagen"):
        asyncio.run(engine.api_session_summarize(session["id"]))
    assert engine.store.get_session(session["id"])["status"] == "done"


def test_cpu_fallback_is_reported(engine):
    engine.transcriber.device = "cpu"
    engine.settings = {**engine.settings, "device": "auto"}
    assert engine._stt_info()["fallback"] is True


def test_one_failing_segment_does_not_stop_the_live_transcript(engine):
    sent = capture(engine)
    calls = {"n": 0}
    real = engine.transcriber.transcribe

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("CUDA out of memory")
        return real(*args, **kwargs)

    engine.transcriber.transcribe = flaky

    def feed():
        engine._system_recorder.pending = np.concatenate([tone(6), silence(1.0), tone(6), silence(1.0), tone(3)])

    session, finished = run_session(engine, feed, source="desktop")
    assert finished["status"] == "done"
    assert len(engine.store.session_segments(session["id"])) == 2  # the first failed, the others still came
    kinds = [m.get("kind") for m in sent if m["type"] == "session_warning"]
    assert "transcribe_error" in kinds


def test_a_failing_tick_does_not_end_the_recording(engine, monkeypatch):
    sent = capture(engine)
    real = engine._session_watchdog
    calls = {"n": 0}

    async def flaky(live):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("kurz weg")
        await real(live)

    monkeypatch.setattr(engine, "_session_watchdog", flaky)

    def feed():
        engine._system_recorder.pending = np.concatenate([tone(6), silence(1.0)])

    session, finished = run_session(engine, feed, ticks=3, source="desktop")
    assert finished["status"] == "done"
    warnings = [m for m in sent if m["type"] == "session_warning"]
    assert any(m.get("kind") == "loop_error" for m in warnings)
    assert any(m.get("clears") == "loop_error" for m in warnings)  # cleared once ticks work again


def test_reconnect_clears_its_own_warning_only(engine):
    sent = capture(engine)
    attempts = {"n": 0}

    def restart():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise OSError("Gerät weg")
        engine._system_recorder.alive = True

    engine._system_recorder.restart = restart

    async def scenario():
        await engine.api_session_start(source="desktop")
        engine._system_recorder.alive = False
        await asyncio.sleep(server.SESSION_TICK_S * 2.5)
        await engine.api_session_stop()

    asyncio.run(scenario())
    warnings = [m for m in sent if m["type"] == "session_warning"]
    assert any(m["kind"] == "stream_lost_them" for m in warnings)
    assert any(m["kind"] == "clear" and m["clears"] == "stream_lost_them" for m in warnings)


def test_device_query_returns_empty_when_the_child_fails(monkeypatch):
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1))
    assert audio.default_loopback_name() == ""


def test_device_query_child_writes_the_name(tmp_path, monkeypatch):
    from engine import __main__ as entry

    monkeypatch.setattr(audio, "query_default_loopback_name", lambda: "Kopfhörer (USB) [Loopback]")
    target = tmp_path / "out.txt"
    with pytest.raises(SystemExit) as stop:
        entry._write_default_loopback(str(target))
    assert stop.value.code == 0
    assert target.read_text(encoding="utf-8") == "Kopfhörer (USB) [Loopback]"


def test_markdown_always_names_the_speaker():
    session = {"title": "VL", "started_at": 0, "ended_at": 10, "source": "desktop"}
    md = export.to_markdown(session, [{"speaker": "them", "start_s": 0.0, "end_s": 5.0, "text": "Hallo."}])
    assert "**Gegenüber** `[00:00]` Hallo." in md


def test_slow_device_query_does_not_block_the_tick(engine, monkeypatch):
    monkeypatch.setattr(server, "DEVICE_CHECK_S", 0.0)

    def slow():
        time.sleep(8)  # far longer than a session tick plus the up to one tick the loop needs to notice a stop
        return "Fake"

    monkeypatch.setattr(server.audio, "default_loopback_name", slow)

    async def scenario():
        session = await engine.api_session_start(source="desktop")
        engine._system_recorder.pending = np.concatenate([tone(6), silence(1.0), tone(3)])
        started = time.monotonic()
        await asyncio.sleep(server.SESSION_TICK_S * 2)
        finished = await engine.api_session_stop()
        return session, finished, time.monotonic() - started

    session, finished, took = asyncio.run(scenario())
    assert finished["status"] == "done"
    assert len(engine.store.session_segments(session["id"])) == 2
    assert took < 5.0  # the session did not wait for the slow child process


def test_live_text_is_on_by_default_for_sessions(engine):
    sent = capture(engine)

    async def scenario():
        await engine.api_session_start(source="desktop")
        engine._system_recorder.pending = tone(4)  # speech without a pause, nothing is cut yet
        await asyncio.sleep(server.SESSION_TICK_S * 2.5)
        await engine.api_session_stop()

    asyncio.run(scenario())
    previews = [m for m in sent if m["type"] == "session_preview" and m["speaker"] == "them"]
    assert previews and previews[0]["text"].startswith("abschnitt")


def test_live_text_waits_while_finished_segments_are_queued(engine, monkeypatch):
    sent = capture(engine)

    async def scenario():
        await engine.api_session_start(source="desktop")
        engine._live.queued_s = server.PREVIEW_MAX_LAG_S + 1  # the model is behind
        engine._system_recorder.pending = tone(4)
        await asyncio.sleep(server.SESSION_TICK_S * 2.5)
        await engine.api_session_stop()

    asyncio.run(scenario())
    assert not [m for m in sent if m["type"] == "session_preview"]


def test_new_sessions_use_the_saved_live_choice(engine):
    engine.settings = {**engine.settings, "session_live_text": False}
    sent = capture(engine)

    async def scenario():
        await engine.api_session_start(source="desktop")
        engine._system_recorder.pending = tone(4)
        await asyncio.sleep(server.SESSION_TICK_S * 2.5)
        await engine.api_session_stop()

    asyncio.run(scenario())
    assert not [m for m in sent if m["type"] == "session_preview"]
