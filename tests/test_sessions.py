import numpy as np
import pytest

from engine.audio import SAMPLE_RATE
from engine.sessions import SEGMENT_MAX_S, SEGMENT_MIN_S, SOFT_CUT_WINDOW_S, Segmenter


def tone(seconds: float) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return (0.2 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)


def test_no_segment_before_minimum_length():
    assert Segmenter().feed(tone(SEGMENT_MIN_S - 1)) == []


def test_cuts_in_the_middle_of_a_pause():
    segmenter = Segmenter()
    out = segmenter.feed(np.concatenate([tone(6), silence(1.0), tone(3)]))

    assert len(out) == 1
    assert out[0].start_s == 0.0
    assert 6.2 < out[0].end_s < 6.8
    rest = segmenter.flush()
    assert rest.start_s == pytest.approx(out[0].end_s)


def test_cut_without_pause_stays_within_the_maximum():
    out = Segmenter().feed(tone(SEGMENT_MAX_S + 2))

    assert len(out) == 1
    assert SEGMENT_MAX_S - SOFT_CUT_WINDOW_S <= out[0].end_s <= SEGMENT_MAX_S


def test_cut_without_pause_lands_on_the_quietest_moment():
    loud = tone(SEGMENT_MAX_S + 2)
    dip_at = 27.0
    start = int(dip_at * SAMPLE_RATE)
    loud[start:start + int(0.2 * SAMPLE_RATE)] *= 0.1  # quieter, but no real pause

    out = Segmenter().feed(loud)

    assert out[0].end_s == pytest.approx(dip_at + 0.05, abs=0.1)


def test_short_pause_does_not_cut():
    assert Segmenter().feed(np.concatenate([tone(6), silence(0.3), tone(6)])) == []


def test_small_pieces_give_the_same_cut():
    audio_in = np.concatenate([tone(6), silence(1.0), tone(3)])
    segmenter = Segmenter()
    out = []
    for start in range(0, audio_in.size, 1600):
        out += segmenter.feed(audio_in[start:start + 1600])

    assert len(out) == 1
    assert 6.2 < out[0].end_s < 6.8


def test_flush_skips_pure_silence():
    segmenter = Segmenter()
    segmenter.feed(silence(3))
    assert segmenter.flush() is None


def test_flush_returns_remaining_audio_even_when_short():
    segmenter = Segmenter()
    segmenter.feed(tone(2))
    rest = segmenter.flush()
    assert rest.start_s == 0.0
    assert rest.end_s == pytest.approx(2.0)
