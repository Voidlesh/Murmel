from engine import llm

SUMMARY_WITH_TASKS = "## Zusammenfassung\nKurz.\n\n## Aufgaben\n- Angebot schicken\n- Termin buchen"


def test_split_words_into_blocks():
    text = " ".join(f"w{i}" for i in range(3500))
    assert [len(b.split()) for b in llm.split_words(text, 1500)] == [1500, 1500, 500]


def test_short_transcript_needs_one_request(monkeypatch):
    calls = []

    def fake_chat(cfg, messages, max_tokens, temperature=0.1, timeout=None):
        calls.append(messages)
        return SUMMARY_WITH_TASKS

    monkeypatch.setattr(llm, "_chat", fake_chat)
    summary, items = llm.summarize_session("hallo welt", {"base_url": "http://x/v1"})

    assert len(calls) == 1
    assert summary == "Kurz."
    assert items == ["Angebot schicken", "Termin buchen"]


def test_long_transcript_is_summarized_in_blocks_then_merged(monkeypatch):
    calls = []

    def fake_chat(cfg, messages, max_tokens, temperature=0.1, timeout=None):
        calls.append(messages[-1]["content"])
        return "## Zusammenfassung\nTeil.\n\n## Aufgaben\n- Eins"

    monkeypatch.setattr(llm, "_chat", fake_chat)
    summary, items = llm.summarize_session(" ".join(["wort"] * 3500), {"base_url": "http://x/v1"})

    assert len(calls) == 4  # three blocks, then one merge request
    assert items == ["Eins"]


def test_missing_task_section_yields_no_items(monkeypatch):
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: "## Zusammenfassung\nNur Text.")
    assert llm.summarize_session("hallo", {"base_url": "http://x/v1"}) == ("Nur Text.", [])
