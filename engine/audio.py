"""Microphone capture at 16 kHz mono with live level callbacks."""
from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
import wave
from pathlib import Path
from typing import Callable

import numpy as np
import pyaudiowpatch as pyaudio
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BLOCK = 800  # 50 ms
SILENCE_RMS = 0.004  # RMS below this counts as silence
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


def _resample(samples: np.ndarray, rate: int) -> np.ndarray:
    """Linear resampling to SAMPLE_RATE. Good enough for speech; sounddevice cannot do WASAPI loopback."""
    if rate == SAMPLE_RATE:
        return samples
    out_len = int(samples.size * SAMPLE_RATE / rate)
    positions = np.arange(out_len) * (rate / SAMPLE_RATE)
    return np.interp(positions, np.arange(samples.size), samples).astype(np.float32)


LOWPASS_TAPS = 63


def _lowpass_kernel(rate: int) -> np.ndarray:
    """Windowed-sinc low-pass just below the new Nyquist, so 48 kHz content does not alias into speech."""
    cutoff = 0.45 * SAMPLE_RATE / rate  # as a fraction of the source rate
    n = np.arange(LOWPASS_TAPS) - (LOWPASS_TAPS - 1) / 2
    kernel = 2 * cutoff * np.sinc(2 * cutoff * n) * np.hamming(LOWPASS_TAPS)
    return (kernel / kernel.sum()).astype(np.float32)


class StreamResampler:
    """Block-wise low-pass + resampling that stays continuous across callback blocks."""

    def __init__(self, rate: int) -> None:
        self._rate = rate
        self._kernel = _lowpass_kernel(rate) if rate > SAMPLE_RATE else None
        self._history = np.zeros(LOWPASS_TAPS - 1, dtype=np.float32)
        self._pos = 0.0  # position of the next output sample, in source samples relative to the block start

    def process(self, block: np.ndarray) -> np.ndarray:
        if self._rate == SAMPLE_RATE:
            return block.astype(np.float32, copy=False)
        if self._kernel is not None:
            padded = np.concatenate([self._history, block.astype(np.float32, copy=False)])
            self._history = padded[-(LOWPASS_TAPS - 1):]
            block = np.convolve(padded, self._kernel, mode="valid").astype(np.float32)
        step = self._rate / SAMPLE_RATE
        positions = np.arange(self._pos, block.size - 1, step)
        out = np.interp(positions, np.arange(block.size), block).astype(np.float32)
        next_pos = positions[-1] + step if positions.size else self._pos
        self._pos = next_pos - block.size
        return out


def query_default_loopback_name() -> str:
    """Name of the playback device Windows uses right now, as seen by a PortAudio started in this process."""
    pa = pyaudio.PyAudio()
    try:
        return str(pa.get_default_wasapi_loopback()["name"])
    finally:
        pa.terminate()


DEVICE_QUERY_FLAG = "--default-loopback"
DEVICE_QUERY_TIMEOUT_S = 15.0


def default_loopback_name() -> str:
    """The current default playback device, asked in a short-lived child process.

    PortAudio is initialized once per process and keeps the device list from that moment; while the
    session's own loopback stream is open, a new PyAudio in this process would still report the old device.
    A fresh process sees the real current default. Returns '' if the question cannot be answered."""
    import subprocess
    import sys
    import tempfile

    out = Path(tempfile.gettempdir()) / f"murmel-device-{os.getpid()}.txt"
    out.unlink(missing_ok=True)
    if getattr(sys, "frozen", False):
        command = [sys.executable, DEVICE_QUERY_FLAG, str(out)]
    else:
        command = [sys.executable, "-m", "engine", DEVICE_QUERY_FLAG, str(out)]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    root = Path(__file__).resolve().parent.parent
    try:
        result = subprocess.run(  # windowed builds may have no stdout, so the answer comes back in a file
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=DEVICE_QUERY_TIMEOUT_S, creationflags=flags,
            cwd=None if getattr(sys, "frozen", False) else str(root),
        )
        if result.returncode != 0 or not out.exists():
            return ""
        return out.read_text(encoding="utf-8").strip()
    except (OSError, subprocess.SubprocessError):
        log.debug("Gerätesuche fehlgeschlagen", exc_info=True)
        return ""
    finally:
        with contextlib.suppress(OSError):
            out.unlink(missing_ok=True)


class LoopbackStream:
    """What the default playback device plays (Discord, Teams, browsers), via PyAudioWPatch's WASAPI loopback."""

    def __init__(self, callback: Callable[..., None]) -> None:
        self._callback = callback
        self._pa = pyaudio.PyAudio()
        try:
            device = self._pa.get_default_wasapi_loopback()
        except OSError as exc:
            self._pa.terminate()
            raise RuntimeError("Keine Wiedergabe gefunden, Systemaudio ist nicht verfügbar") from exc
        self.device_name = str(device["name"])
        self.errors = 0  # status flags reported by WASAPI (overflow, device trouble)
        self._rate = int(device["defaultSampleRate"])
        self._channels = int(device["maxInputChannels"])
        self._resampler = StreamResampler(self._rate)
        self._stream = self._pa.open(
            format=pyaudio.paFloat32, channels=self._channels, rate=self._rate, input=True,
            input_device_index=device["index"], frames_per_buffer=BLOCK * self._rate // SAMPLE_RATE,
            stream_callback=self._on_audio, start=False,
        )

    def _on_audio(self, in_data: bytes, _frame_count: int, _time_info, status: int):
        if status:
            self.errors += 1
        frames = np.frombuffer(in_data, dtype=np.float32).reshape(-1, self._channels)
        mono = self._resampler.process(frames.mean(axis=1, dtype=np.float32))
        self._callback(mono.reshape(-1, 1), mono.size, None, status or None)
        return None, pyaudio.paContinue

    @property
    def active(self) -> bool:
        return bool(self._stream.is_active())

    def start(self) -> None:
        self._stream.start_stream()

    def stop(self) -> None:
        self._stream.stop_stream()

    def close(self) -> None:
        self._stream.close()
        self._pa.terminate()


GAP_FILL_S = 0.5  # loopback delivers nothing while nothing plays; gaps longer than this become silence
GAP_KEEP_S = 0.2  # what is left unfilled, so late blocks of real audio do not overlap the padding


class Recorder:
    def __init__(self, on_level: Callable[[np.ndarray], None]) -> None:
        self._on_level = on_level
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | LoopbackStream | None = None
        self._loopback = False
        self._fill = False
        self._device: int | None = None
        self._lock = threading.Lock()
        self._started = 0.0  # monotonic start, for gap filling
        self._received = 0  # samples received or padded since start
        self.level_db = SILENCE_DB  # loudness of the newest block, for live meters
        self.level_at = 0.0  # monotonic time of the newest block
        self.status_errors = 0

    @property
    def active(self) -> bool:
        return self._stream is not None

    @property
    def device_name(self) -> str:
        if isinstance(self._stream, LoopbackStream):
            return self._stream.device_name
        if self._stream is None:
            return ""
        try:
            return str(sd.query_devices(self._device, "input")["name"])
        except Exception:  # noqa: BLE001 - only informative
            return ""

    def start(self, device: int | None = None, loopback: bool = False, fill_gaps: bool = False) -> None:
        """fill_gaps: pad missing time with silence (sessions), so the timeline survives silence and restarts."""
        with self._lock:
            if self._stream:
                return
            self._chunks = []
            self._loopback = loopback
            self._fill = fill_gaps or loopback
            self._device = device
            self._stream = self._open_stream(device, loopback)
            self._started = time.monotonic()
            self._received = 0
            self.level_db, self.level_at, self.status_errors = SILENCE_DB, 0.0, 0
            self._stream.start()

    def restart(self) -> None:
        """Reopen the stream (lost device, new default output) without losing recorded samples or the timeline."""
        with self._lock:
            old, self._stream = self._stream, None
        if old:
            with contextlib.suppress(Exception):
                old.stop()
            with contextlib.suppress(Exception):
                old.close()
        stream = self._open_stream(self._device, self._loopback)
        with self._lock:
            self._stream = stream
        stream.start()

    def healthy(self) -> bool:
        """False when the stream died (device unplugged, driver error). Silence alone is healthy."""
        stream = self._stream
        if stream is None:
            return False
        try:
            return bool(stream.active)
        except Exception:  # noqa: BLE001 - a broken stream may raise on any access
            return False

    def _open_stream(self, device: int | None, loopback: bool) -> sd.InputStream | LoopbackStream:
        if loopback:
            return LoopbackStream(self._callback)
        return sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=BLOCK,
            device=device, callback=self._callback,
        )

    def _callback(self, data: np.ndarray, _frames: int, _time, status) -> None:
        if status:
            self.status_errors += 1
            log.debug("audio status: %s", status)
        mono = data.mean(axis=1, dtype=np.float32)  # loopback may deliver stereo, the mic mono
        with self._lock:
            self._chunks.append(mono)
            self._received += mono.size
        if mono.size:
            rms = float(np.sqrt(np.mean(mono**2)))
            self.level_db = 20.0 * np.log10(rms) if rms > 1e-9 else SILENCE_DB
            self.level_at = time.monotonic()
        if not self._loopback:  # the island bars follow the microphone only
            self._on_level(band_levels_db(mono))

    def _fill_gaps(self) -> None:
        """Pad the loopback with silence for the time nothing played, so its timeline follows the wall clock."""
        if not self._fill or not self._started:
            return
        expected = int((time.monotonic() - self._started) * SAMPLE_RATE)
        missing = expected - self._received
        if missing > GAP_FILL_S * SAMPLE_RATE:
            pad = missing - int(GAP_KEEP_S * SAMPLE_RATE)
            self._chunks.append(np.zeros(pad, dtype=np.float32))
            self._received += pad

    def drain(self) -> np.ndarray:
        """Take the samples recorded since the last drain, so long sessions do not grow in memory."""
        with self._lock:
            self._fill_gaps()
            chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)

    def peek(self, max_samples: int) -> np.ndarray:
        """The newest samples of the running recording, without taking them away from stop()."""
        with self._lock:
            chunks = list(self._chunks)
        tail: list[np.ndarray] = []
        total = 0
        for chunk in reversed(chunks):
            tail.append(chunk)
            total += chunk.size
            if total >= max_samples:
                break
        if not tail:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(tail[::-1])[-max_samples:]

    def stop(self) -> np.ndarray:
        with self._lock:
            stream, self._stream = self._stream, None
        if stream:
            with contextlib.suppress(Exception):
                stream.stop()
            with contextlib.suppress(Exception):
                stream.close()
        out = self.drain()
        self._started = 0.0
        return out


def is_silent(audio: np.ndarray, threshold: float = SILENCE_RMS) -> bool:
    return audio.size == 0 or float(np.sqrt(np.mean(audio**2))) < threshold


WAV_HEADER_BYTES = 44
WAV_SYNC_S = 5.0  # header and data hit the disk at least this often, so a crash loses seconds, not the file


def _wav_header(data_bytes: int) -> bytes:
    import struct

    return struct.pack(
        "<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + data_bytes, b"WAVE", b"fmt ", 16, 1, 1,
        SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16, b"data", data_bytes,
    )


class WavWriter:
    """Writes 16 kHz mono PCM while a session is recorded, so long audio never sits fully in memory.

    The header is rewritten every few seconds, so the file stays playable if the engine or the PC dies."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file = open(path, "wb")  # noqa: SIM115 - closed in close()
        self._file.write(_wav_header(0))
        self._data_bytes = 0
        self._synced = time.monotonic()

    @property
    def seconds(self) -> float:
        return self._data_bytes / 2 / SAMPLE_RATE

    def write(self, samples: np.ndarray) -> None:
        if not samples.size:
            return
        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
        self._file.write(pcm.tobytes())
        self._data_bytes += pcm.size * 2
        if time.monotonic() - self._synced >= WAV_SYNC_S:
            self.sync()

    def sync(self) -> None:
        self._file.seek(0)
        self._file.write(_wav_header(self._data_bytes))
        self._file.seek(0, 2)
        self._file.flush()
        with contextlib.suppress(OSError):
            os.fsync(self._file.fileno())
        self._synced = time.monotonic()

    def close(self) -> None:
        if self._file.closed:
            return
        self.sync()
        self._file.close()


def repair_wav(path: Path) -> bool:
    """Fix the size fields of a WAV cut off by a crash. Returns True if the file was changed."""
    try:
        size = path.stat().st_size
        if size < WAV_HEADER_BYTES:
            return False
        data_bytes = (size - WAV_HEADER_BYTES) // 2 * 2
        with open(path, "r+b") as f:
            header = f.read(WAV_HEADER_BYTES)
            if header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                return False
            fixed = _wav_header(data_bytes)
            if header == fixed:
                return False
            f.seek(0)
            f.write(fixed)
        return True
    except OSError:
        log.exception("WAV-Reparatur fehlgeschlagen: %s", path)
        return False


def read_wav_chunks(path: Path, seconds: float = 30.0):
    """Yield float32 blocks of a 16 kHz mono 16-bit WAV, so hour-long files are never fully in memory."""
    with wave.open(str(path), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (SAMPLE_RATE, 1, 2):
            raise ValueError("Nur 16-kHz-Mono-WAV wird blockweise gelesen")
        frames = int(seconds * SAMPLE_RATE)
        while True:
            raw = wav.readframes(frames)
            if not raw:
                return
            yield np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def save_wav(audio: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
