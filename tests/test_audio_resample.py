import numpy as np

from engine import audio


def test_resample_keeps_duration_and_speech_level():
    rate = 48000
    t = np.arange(rate) / rate
    tone = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)

    out = audio._resample(tone, rate)

    assert out.size == audio.SAMPLE_RATE
    level_in = float(np.sqrt(np.mean(tone**2)))
    level_out = float(np.sqrt(np.mean(out**2)))
    assert abs(level_out - level_in) < 0.01


def test_resample_is_identity_at_target_rate():
    samples = np.linspace(-1, 1, 1000, dtype=np.float32)

    assert audio._resample(samples, audio.SAMPLE_RATE) is samples
