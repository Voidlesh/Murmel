"""Transcribe a 16 kHz mono wav with the warm model and print latency."""
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.stt import Transcriber  # noqa: E402

with wave.open(sys.argv[1]) as w:
    audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
tr = Transcriber(sys.argv[2] if len(sys.argv) > 2 else "large-v3-turbo")
print(f"device={tr.device} audio={audio.size / 16000:.1f}s")
for beam in (1, 1, 5):
    r = tr.transcribe(audio, "de", beam, [])
    print(f"beam={beam} {r.process_ms} ms -> {r.text}")
