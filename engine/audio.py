"""Microphone capture at 16 kHz mono with live level callbacks."""
from __future__ import annotations

import logging
import threading
import wave
from pathlib import Path
from typing import Callable

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BLOCK = 800  # 50 ms
SILENCE_DB = -100.0
FLOOR_MIN_DB = -60.0
RANGE_DB = 20.0


BAND_COUNT = 10
BAND_EDGES_HZ = np.geomspace(120.0, 3600.0, BAND_COUNT + 1)  # speech range, log-spaced low -> high pitch
BAND_FLOOR_MIN_DB = -70.0
BAND_RANGE_DB = 40.0


def band_levels_db(block: np.ndarray) -> np.ndarray:
    """Loudness (dBFS) of BAND_COUNT frequency bands, so the bars follow pitch as well as volume."""
    window = np.hanning(block.size)
    spectrum = np.abs(np.fft.rfft(block * window)) * 2.0 / window.sum()
    freqs = np.fft.rfftfreq(block.size, 1.0 / SAMPLE_RATE)
    bands = np.empty(BAND_COUNT)
    for i in range(BAND_COUNT):
        mask = (freqs >= BAND_EDGES_HZ[i]) & (freqs < BAND_EDGES_HZ[i + 1])
        power = float(np.sum(spectrum[mask] ** 2)) if mask.any() else 0.0
        bands[i] = 10.0 * np.log10(power) if power > 1e-12 else SILENCE_DB
    return bands


class LevelScaler:
    """Loudness (dBFS) -> 0..1 relative to the quietest level seen (adaptive noise floor)."""

    def __init__(self, floor_min_db: float = FLOOR_MIN_DB, range_db: float = RANGE_DB) -> None:
        self._floor_min = floor_min_db
        self._range = range_db
        self._floor = 0.0

    def reset(self) -> None:
        self._floor = 0.0

    def scale(self, db: float) -> float:
        if db < self._floor:
            self._floor = max(self._floor_min, db)
        return max(0.0, min(1.0, (db - self._floor) / self._range))


def list_microphones() -> list[dict]:
    default_in = sd.default.device[0]
    seen: set[str] = set()
    mics = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] <= 0 or dev["name"] in seen:
            continue
        hostapi = sd.query_hostapis(dev["hostapi"])["name"]
        if "WDM-KS" in hostapi:
            continue
        seen.add(dev["name"])
        mics.append({"id": idx, "name": dev["name"], "default": idx == default_in})
    return mics


class Recorder:
    def __init__(self, on_level: Callable[[np.ndarray], None]) -> None:
        self._on_level = on_level
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._stream is not None

    def start(self, device: int | None = None) -> None:
        with self._lock:
            if self._stream:
                return
            self._chunks = []
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=BLOCK,
                device=device, callback=self._callback,
            )
            self._stream.start()

    def _callback(self, data: np.ndarray, _frames: int, _time, status) -> None:
        if status:
            log.debug("audio status: %s", status)
        mono = data[:, 0].copy()
        self._chunks.append(mono)
        self._on_level(band_levels_db(mono))

    def stop(self) -> np.ndarray:
        with self._lock:
            stream, self._stream = self._stream, None
        if stream:
            stream.stop()
            stream.close()
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._chunks)


def is_silent(audio: np.ndarray, threshold: float = 0.004) -> bool:
    return audio.size == 0 or float(np.sqrt(np.mean(audio**2))) < threshold


def save_wav(audio: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
