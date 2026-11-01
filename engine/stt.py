"""faster-whisper wrapper that keeps the model warm on the GPU (CPU fallback)."""
from __future__ import annotations

import logging
import os
import site
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

CPU_FALLBACK_MODEL = "small"
# Measured on a GTX 1660 Super: int8_float32 ~1.0 s vs float16 ~7.5 s for 10 s of speech.
# GTX 16xx cards have crippled FP16 paths, so int8 weights + fp32 compute wins.
CUDA_COMPUTE_TYPE = "int8_float32"
MAX_PROMPT_WORDS = 60


def _cuda_roots() -> list[str]:
    """Where the nvidia-* DLLs live: site-packages in dev, the bundle folder in the PyInstaller build."""
    bundle_dir = getattr(sys, "_MEIPASS", None)
    return ([bundle_dir] if bundle_dir else []) + site.getsitepackages()


def _register_cuda_dlls() -> None:
    """pip's nvidia-* wheels ship DLLs that Windows will not find on its own."""
    for root in _cuda_roots():
        for sub in ("cublas", "cudnn", "cuda_nvrtc"):
            bin_dir = Path(root) / "nvidia" / sub / "bin"
            if bin_dir.is_dir():
                os.add_dll_directory(str(bin_dir))
                os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


_register_cuda_dlls()

from faster_whisper import WhisperModel  # noqa: E402  (needs the DLL paths above)


@dataclass(frozen=True)
class SttResult:
    text: str
    language: str
    process_ms: int


class Transcriber:
    def __init__(self, model_name: str, device: str = "auto") -> None:
        self.model_name = model_name
        self.device = "cpu"
        self._lock = threading.Lock()
        self._model = self._load(model_name, device)

    def _load(self, model_name: str, device: str) -> WhisperModel:
        if device in ("auto", "cuda"):
            try:
                model = WhisperModel(model_name, device="cuda", compute_type=CUDA_COMPUTE_TYPE)
                self.device = "cuda"
                self._warmup(model)
                return model
            except Exception:  # noqa: BLE001 - any CUDA/cuDNN failure means fall back
                log.exception("CUDA nicht nutzbar, falle auf CPU zurück")
                if device == "cuda":
                    raise
        self.model_name = model_name if device == "cpu" else CPU_FALLBACK_MODEL
        model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        self._warmup(model)
        return model

    @staticmethod
    def _warmup(model: WhisperModel) -> None:
        segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), beam_size=1, language="de")
        list(segments)

    def transcribe(self, audio: np.ndarray, language: str | None, beam_size: int, vocabulary: list[str]) -> SttResult:
        with self._lock:  # live previews and the final text may run at the same time, the model is not thread-safe
            return self._transcribe(audio, language, beam_size, vocabulary)

    def _transcribe(self, audio: np.ndarray, language: str | None, beam_size: int, vocabulary: list[str]) -> SttResult:
        started = time.perf_counter()
        prompt = ", ".join(vocabulary[:MAX_PROMPT_WORDS]) or None
        segments, info = self._model.transcribe(
            audio,
            language=None if language in (None, "", "auto") else language,
            beam_size=max(1, int(beam_size)),
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,
            without_timestamps=True,
            # hotwords biased too hard in tests ("das Team" -> "das Tim"); the prompt alone is enough
            initial_prompt=prompt,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return SttResult(text, info.language, int((time.perf_counter() - started) * 1000))
