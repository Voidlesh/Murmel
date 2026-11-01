"""Load the configured Whisper model and time a transcription of synthetic + sample audio."""
import logging
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.basicConfig(level=logging.INFO)

from engine.stt import Transcriber  # noqa: E402

t0 = time.perf_counter()
tr = Transcriber(sys.argv[1] if len(sys.argv) > 1 else "large-v3-turbo")
print(f"loaded {tr.model_name} on {tr.device} in {time.perf_counter() - t0:.1f}s")
audio = (np.random.default_rng(0).standard_normal(16000 * 10) * 0.01).astype(np.float32)
for _ in range(2):
    r = tr.transcribe(audio, "de", 1, ["Murmel"])
    print(f"10s noise -> {r.process_ms} ms, text={r.text!r}")
