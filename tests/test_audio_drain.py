import numpy as np

from engine import audio


def test_drain_returns_only_samples_recorded_since_last_call():
    recorder = audio.Recorder(lambda bands: None)
    recorder._callback(np.full((800, 1), 0.1, dtype=np.float32), 800, None, None)

    assert recorder.drain().size == 800
    assert recorder.drain().size == 0
