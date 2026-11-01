import sys, time, wave
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine.stt  # registers DLLs
from faster_whisper import WhisperModel
with wave.open(sys.argv[1]) as w:
    audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
for ct in sys.argv[2].split(","):
    m = WhisperModel(sys.argv[3] if len(sys.argv) > 3 else "large-v3-turbo", device="cuda", compute_type=ct)
    for i in range(2):
        t = time.perf_counter(); segs, _ = m.transcribe(audio, language="de", beam_size=1, without_timestamps=True, condition_on_previous_text=False)
        txt = " ".join(s.text for s in segs); dt = time.perf_counter() - t
    print(f"{ct}: {dt*1000:.0f} ms  {txt[:60]!r}", flush=True)
    del m
