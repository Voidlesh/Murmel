import pytest

from engine import llm
from engine.store import Store
from engine.style import Example, StyleContext


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


def _add(store, text, category="work"):
    return store.add_transcript({
        "raw_text": "roh " + text, "text": text, "words": 2, "duration_s": 1.0, "category": category,
    })


def test_first_edit_keeps_murmels_original_output(store):
    item = _add(store, "Hallo Welt.")
    store.update_transcript_text(item["id"], "Hallo Welt", 2)
    store.update_transcript_text(item["id"], "Hallo Welt!", 2)
    stored = store.get_transcript(item["id"])
    assert stored["auto_text"] == "Hallo Welt."
    assert stored["text"] == "Hallo Welt!"


def test_style_edits_only_returns_edited_rows_of_one_category(store):
    edited = _add(store, "Eins.")
    store.update_transcript_text(edited["id"], "Eins", 1)
    _add(store, "Unberührt.")
    other = _add(store, "Privat.", category="personal")
    store.update_transcript_text(other["id"], "Privat", 1)
    rows = store.style_edits("work")
    assert [(r["auto_text"], r["text"]) for r in rows] == [("Eins.", "Eins")]


def test_polish_sends_rules_and_examples_as_chat_messages(monkeypatch):
    captured = {}

    def fake_post(url, payload, timeout):
        captured.update(payload)
        return {"choices": [{"message": {"content": "Ok"}}]}

    monkeypatch.setattr(llm, "_post", fake_post)
    style = StyleContext(final_period=False, examples=(Example("roh eins", "Eins"),))
    llm.polish("neu drei wörter", "formal", {"base_url": "http://x/v1", "model": "m"}, [], style)
    system = captured["messages"][0]["content"]
    assert "Do not put a period at the end of the text." in system
    assert captured["messages"][1] == {"role": "user", "content": "<dictation>\nroh eins\n</dictation>"}
    assert captured["messages"][2] == {"role": "assistant", "content": "Eins"}
    assert captured["messages"][-1]["content"].startswith("<dictation>\nneu drei")
