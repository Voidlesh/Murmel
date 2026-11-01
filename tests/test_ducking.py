import json

from engine.ducking import Ducker


def test_recover_leftover_without_state_file_is_a_noop(tmp_path):
    Ducker(tmp_path / "duck_state.json").recover_leftover()


def test_recover_leftover_clears_state_file(tmp_path):
    state = tmp_path / "duck_state.json"
    state.write_text(json.dumps({"999999": [1.0, 0.15]}), encoding="utf-8")
    Ducker(state).recover_leftover()
    assert not state.exists()
