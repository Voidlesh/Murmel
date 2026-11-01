from engine.audio import LevelScaler


def test_scaler_uses_20db_above_the_quietest_level():
    scaler = LevelScaler()
    assert scaler.scale(-50) == 0.0          # first sample becomes the floor
    assert scaler.scale(-40) == 0.5
    assert scaler.scale(-20) == 1.0


def test_scaler_floor_never_drops_below_minus_60():
    scaler = LevelScaler()
    scaler.scale(-100)
    assert scaler.scale(-50) == 0.5


def test_band_levels_follow_pitch():
    import numpy as np

    from engine.audio import SAMPLE_RATE, band_levels_db

    t = np.arange(800) / SAMPLE_RATE
    low = band_levels_db(0.3 * np.sin(2 * np.pi * 200 * t))
    high = band_levels_db(0.3 * np.sin(2 * np.pi * 2500 * t))
    assert int(np.argmax(low)) < 3
    assert int(np.argmax(high)) > 6


def test_louder_signal_gives_higher_band_levels():
    import numpy as np

    from engine.audio import SAMPLE_RATE, band_levels_db

    t = np.arange(800) / SAMPLE_RATE
    quiet = band_levels_db(0.02 * np.sin(2 * np.pi * 300 * t)).max()
    loud = band_levels_db(0.4 * np.sin(2 * np.pi * 300 * t)).max()
    assert loud - quiet > 20
