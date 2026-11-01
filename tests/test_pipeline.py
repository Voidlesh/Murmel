import copy

from engine.config import DEFAULTS
from engine.pipeline import process
from engine.textproc import Correction, Snippet


def settings(**over):
    s = copy.deepcopy(DEFAULTS)
    s.update(over)
    return s


def test_full_rule_pipeline():
    r = process(
        "Äh, ich nutze wisper flow, neue Zeile meine mail",
        "other",
        settings(),
        [Correction("wisper flow", "Wispr Flow")],
        [Snippet("meine mail", "levi@example.com")],
        [],
    )
    assert r.text == "Ich nutze Wispr Flow\nlevi@example.com"
    assert r.polished_by_llm is False


def test_personal_category_uses_casual_tone():
    r = process("Bin gleich da.", "personal", settings(), [], [], [])
    assert r.text == "Bin gleich da"


def test_llm_used_when_enabled_and_falls_back_on_error():
    s = settings()
    s["llm"] = {**s["llm"], "enabled": True}

    def ok(text, tone, cfg, vocab):
        return "Poliert: " + text

    def boom(*_):
        raise RuntimeError("down")

    assert process("eins zwei drei vier", "other", s, [], [], [], ok).text == "Poliert: Eins zwei drei vier."
    fallback = process("eins zwei drei vier", "other", s, [], [], [], boom)
    assert fallback.text == "Eins zwei drei vier." and not fallback.polished_by_llm


def test_fix_counters():
    r = process("Äh ich nutze wisper heute", "other", settings(), [Correction("wisper", "Wispr")], [], [])
    assert r.text == "Ich nutze Wispr heute."
    assert r.fixes_dict == 1
    assert r.fixes_words == 1  # the removed filler


def test_corrections_applied_after_llm():
    s = settings()
    s["llm"] = {**s["llm"], "enabled": True}
    r = process("ich mag git hub sehr", "other", s, [Correction("git hub", "GitHub")], [], [], lambda t, *_: t)
    assert "GitHub" in r.text
