from engine.pipeline import process
from engine.style import MAX_EXAMPLES, StyleContext, apply_final_period, build_context
from engine.config import DEFAULTS
import copy


def edit(auto, text, raw="roh"):
    return {"raw_text": raw, "auto_text": auto, "text": text}


def test_no_rows_means_no_preference():
    ctx = build_context([])
    assert ctx == StyleContext()
    assert ctx.rule_lines() == []


def test_learns_to_drop_final_period_after_repeated_edits():
    rows = [edit("Hallo Welt.", "Hallo Welt")] * 3
    assert build_context(rows).final_period is False


def test_learns_to_keep_final_period_after_repeated_edits():
    rows = [edit("Hallo Welt", "Hallo Welt.")] * 3
    assert build_context(rows).final_period is True


def test_single_edit_is_not_enough():
    assert build_context([edit("Hallo Welt.", "Hallo Welt")]).final_period is None


def test_mixed_edits_below_share_threshold_give_no_preference():
    rows = [edit("A.", "A")] * 3 + [edit("B.", "B.")] * 3
    assert build_context(rows).final_period is None


def test_examples_are_newest_first_and_capped_and_skip_long_texts():
    rows = [edit("x", f"Text {i}", raw=f"Diktat {i}") for i in range(MAX_EXAMPLES + 2)]
    rows.insert(0, edit("x", "y" * 500, raw="z"))
    examples = build_context(rows).examples
    assert len(examples) == MAX_EXAMPLES
    assert examples[0].final == "Text 0"


def test_apply_final_period():
    assert apply_final_period("Hallo.", False) == "Hallo"
    assert apply_final_period("Hallo!", False) == "Hallo!"
    assert apply_final_period("Hallo", True) == "Hallo."
    assert apply_final_period("Hallo?", True) == "Hallo?"
    assert apply_final_period("Hallo", None) == "Hallo"


def test_learned_preference_overrides_formal_tone_in_pipeline():
    s = copy.deepcopy(DEFAULTS)
    r = process("Bin gleich da", "work", s, [], [], [], style=StyleContext(final_period=False))
    assert r.text == "Bin gleich da"
