import asyncio

import numpy as np
import pytest

from engine import config, server
from engine.audio import SAMPLE_RATE


class HoldingRecorder:
    """Stands in for the microphone while the key is held: peek() shows what has come so far."""

    def __init__(self, samples: np.ndarray) -> None:
        self.samples = samples

    def peek(self, max_samples: int) -> np.ndarray:
        return self.samples[-max_samples:]


class FakeTranscriber:
    def transcribe(self, audio, language, beam_size, vocabulary):
        from engine.stt import SttResult

        return SttResult(f"zwischenstand {audio.size}", "de", 1)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "PREVIEW_INTERVAL_S", 0.05)
    eng = server.Engine()
    account = eng.accounts.register("Ann", "ann@example.de", "geheim123")
    eng._activate(account)
    eng.settings = {**eng.settings, "session_live_preview": True}
    eng.transcriber = FakeTranscriber()
    eng.recorder = HoldingRecorder(np.full(SAMPLE_RATE * 2, 0.2, dtype=np.float32))
    return eng


def test_dictation_preview_sends_the_text_so_far(engine):
    sent = []

    async def capture(msg):
        sent.append(msg)

    engine.broadcast = capture

    async def scenario():
        engine._dictation_preview = asyncio.create_task(engine._dictation_preview_loop())
        for _ in range(200):  # wait for the first text instead of a fixed sleep
            if any(m["type"] == "dictation_preview" and m["text"] for m in sent):
                break
            await asyncio.sleep(0.02)
        await engine._stop_dictation_preview()

    asyncio.run(scenario())

    texts = [m["text"] for m in sent if m["type"] == "dictation_preview"]
    assert any(text.startswith("zwischenstand") for text in texts)
    assert texts[-1] == ""  # the stop clears the panel
    assert engine._dictation_preview is None


def test_silence_is_not_transcribed_for_the_preview(engine):
    engine.recorder = HoldingRecorder(np.zeros(SAMPLE_RATE * 2, dtype=np.float32))
    sent = []

    async def capture(msg):
        sent.append(msg)

    engine.broadcast = capture

    async def scenario():
        engine._dictation_preview = asyncio.create_task(engine._dictation_preview_loop())
        await asyncio.sleep(0.2)
        await engine._stop_dictation_preview()

    asyncio.run(scenario())

    assert {m["text"] for m in sent if m["type"] == "dictation_preview"} == {""}
