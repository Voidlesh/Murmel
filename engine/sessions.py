"""Cuts a long recording into segments at pauses, so each piece transcribes cleanly."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .audio import SAMPLE_RATE, SILENCE_RMS, is_silent

SEGMENT_MIN_S = 5.0  # no cut before this, so segments are not too short
SEGMENT_MAX_S = 30.0  # hard cut if there is no pause
PAUSE_MIN_S = 0.6  # a silence this long is a natural break
BLOCK_S = 0.1  # resolution for finding pauses


@dataclass(frozen=True)
class Segment:
    start_s: float
    end_s: float
    samples: np.ndarray


class Segmenter:
    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self._rate = sample_rate
        self._buffer = np.zeros(0, dtype=np.float32)
        self._offset = 0  # samples already handed out, so timestamps stay absolute

    def feed(self, samples: np.ndarray) -> list[Segment]:
        self._buffer = np.concatenate([self._buffer, samples.astype(np.float32, copy=False)])
        out: list[Segment] = []
        while (cut := self._cut_index()) is not None:
            out.append(self._take(cut))
        return out

    def flush(self) -> Segment | None:
        if is_silent(self._buffer):
            self._buffer = np.zeros(0, dtype=np.float32)
            return None
        return self._take(self._buffer.size) if self._buffer.size else None

    def _take(self, cut: int) -> Segment:
        piece, self._buffer = self._buffer[:cut], self._buffer[cut:]
        start = self._offset
        self._offset += cut
        return Segment(start / self._rate, self._offset / self._rate, piece)

    def _cut_index(self) -> int | None:
        block = int(BLOCK_S * self._rate)
        min_len, max_len = int(SEGMENT_MIN_S * self._rate), int(SEGMENT_MAX_S * self._rate)
        if self._buffer.size < min_len:
            return None
        pause_blocks = math.ceil(PAUSE_MIN_S / BLOCK_S)
        silent = self._silent_blocks(block)
        run = 0
        for index in range(min_len // block, silent.size):
            run = run + 1 if silent[index] else 0
            if run == pause_blocks:
                return (index - run // 2 + 1) * block  # cut in the middle of the pause
        if self._buffer.size >= max_len:
            return max_len
        return None

    def _silent_blocks(self, block: int) -> np.ndarray:
        count = self._buffer.size // block
        frames = self._buffer[: count * block].reshape(count, block)
        return np.sqrt(np.mean(frames**2, axis=1)) < SILENCE_RMS
