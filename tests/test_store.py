from datetime import date, datetime, timedelta

import pytest

from engine.store import Store, streaks
from engine.textproc import Correction


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


def _ts(d: date, hour: int = 10) -> float:
    return datetime(d.year, d.month, d.day, hour).timestamp()


def test_transcript_roundtrip_and_search(store):
    store.add_transcript({"raw_text": "hallo", "text": "Hallo Welt.", "words": 2, "duration_s": 1.5, "app": "code.exe"})
    store.add_transcript({"raw_text": "x", "text": "Anderer Text", "words": 2, "duration_s": 1.0})
    assert len(store.list_transcripts()) == 2
    assert [t["text"] for t in store.list_transcripts(query="Welt")] == ["Hallo Welt."]


def test_update_and_delete_transcript(store):
    item = store.add_transcript({"raw_text": "a", "text": "a", "words": 1, "duration_s": 1})
    assert store.update_transcript_text(item["id"], "b c", 2)["words"] == 2
    store.delete_transcript(item["id"])
    with pytest.raises(KeyError):
        store.get_transcript(item["id"])


def test_dictionary_upsert_is_case_insensitive(store):
    store.upsert_dictionary("wisper", "Wispr")
    store.upsert_dictionary("Wisper", "Wispr Flow", auto=True)
    entries = store.list_dictionary()
    assert len(entries) == 1
    assert store.corrections() == [Correction("wisper", "Wispr Flow")]


def test_vocabulary_includes_plain_words_and_targets(store):
    store.upsert_dictionary("Murmel")
    store.upsert_dictionary("git hub", "GitHub")
    assert set(store.vocabulary()) == {"Murmel", "GitHub"}


def test_dictionary_suggestions_skip_known_words(store):
    store.add_transcript({"raw_text": "", "text": "Der PR auf GitHub und das LM Studio Setup mit GPT4", "words": 9, "duration_s": 3})
    store.upsert_dictionary("github", "GitHub")
    assert set(store.dictionary_suggestions()) == {"PR", "LM", "GPT4"}


def test_empty_inputs_rejected(store):
    with pytest.raises(ValueError):
        store.upsert_dictionary("  ")
    with pytest.raises(ValueError):
        store.upsert_snippet("x", "")


def test_snippet_upsert_and_edit(store):
    s = store.upsert_snippet("meine mail", "a@b.de")
    store.upsert_snippet("meine adresse", "Straße 1", snippet_id=s["id"])
    assert [x["trigger"] for x in store.list_snippets()] == ["meine adresse"]


def test_stats_words_wpm_and_time_saved(store):
    today = date(2026, 11, 1)
    store.add_transcript({"raw_text": "", "text": "", "words": 150, "duration_s": 60, "app": "slack.exe",
                          "created_at": _ts(today)})
    store.add_transcript({"raw_text": "", "text": "", "words": 50, "duration_s": 20, "app": "code.exe",
                          "created_at": _ts(today - timedelta(days=1), 22)})
    s = store.stats(days=7, typing_wpm=40, today=today)
    assert s["words"] == 200
    assert s["wpm"] == 150
    assert s["time_saved_min"] == pytest.approx(200 / 40 - 80 / 60, abs=0.1)
    assert s["streak"] == 2
    assert s["today_words"] == 150
    assert len(s["daily"]) == 7
    assert s["apps"][0] == {"app": "slack", "words": 150}
    assert s["hours"][22] == 50


def test_streaks():
    t = date(2026, 11, 1)
    days = {t, t - timedelta(days=1), t - timedelta(days=5), t - timedelta(days=6), t - timedelta(days=7)}
    assert streaks(days, t) == (2, 3)
    assert streaks({t - timedelta(days=1)}, t) == (1, 1)
    assert streaks(set(), t) == (0, 0)
