from engine.textproc import (
    Correction,
    Snippet,
    apply_corrections,
    apply_snippets,
    apply_style,
    apply_voice_commands,
    count_words,
    learn_corrections,
    remove_fillers,
)


def test_removes_german_fillers_between_commas():
    assert remove_fillers("Ich, äh, glaube das passt.") == "Ich glaube das passt."


def test_removes_leading_filler_and_recapitalizes():
    assert remove_fillers("Ähm ich komme später.") == "Ich komme später."


def test_keeps_german_word_um():
    assert remove_fillers("Wir treffen uns um drei.") == "Wir treffen uns um drei."


def test_voice_commands_insert_line_breaks():
    assert apply_voice_commands("Hallo Tim, neue Zeile wie geht's") == "Hallo Tim\nWie geht's"
    assert apply_voice_commands("Erster Teil. Neuer Absatz. zweiter Teil") == "Erster Teil\n\nZweiter Teil"


def test_formal_style_adds_final_period():
    assert apply_style("das ist ein Test", "formal") == "Das ist ein Test."


def test_casual_style_drops_final_period():
    assert apply_style("Das ist ein Test.", "casual") == "Das ist ein Test"


def test_very_casual_lowercases_sentence_starts():
    assert apply_style("Das ist gut. Wir sehen uns.", "very_casual") == "das ist gut. wir sehen uns"


def test_very_casual_keeps_acronyms():
    assert apply_style("API ist down.", "very_casual") == "API ist down"


def test_unknown_tone_is_noop():
    assert apply_style("Text.", "weird") == "Text."


def test_corrections_whole_word_case_insensitive():
    corrections = [Correction("wisper flow", "Wispr Flow"), Correction("git hub", "GitHub")]
    assert apply_corrections("Ich nutze wisper Flow und Git Hub.", corrections) == "Ich nutze Wispr Flow und GitHub."


def test_corrections_do_not_touch_substrings():
    assert apply_corrections("Abendessen", [Correction("essen", "Essen")]) == "Abendessen"


def test_snippet_whole_utterance_returns_expansion():
    snippets = [Snippet("meine email", "levi@example.com")]
    assert apply_snippets("Meine E-Mail.", snippets) == "Meine E-Mail."
    assert apply_snippets("Meine Email.", snippets) == "levi@example.com"


def test_snippet_inline_replacement():
    snippets = [Snippet("mein kalender", "https://cal.com/levi")]
    assert apply_snippets("Buch hier: mein Kalender", snippets) == "Buch hier: https://cal.com/levi"


def test_learn_corrections_from_edit():
    learned = learn_corrections("Ich nutze wisper flow jeden Tag", "Ich nutze Wispr Flow jeden Tag")
    assert Correction("wisper", "Wispr") in learned or Correction("wisper flow", "Wispr Flow") in learned


def test_learn_case_only_change():
    assert learn_corrections("ich mag github", "ich mag GitHub") == [Correction("github", "GitHub")]


def test_learn_ignores_large_rewrites():
    assert learn_corrections("a b c d e", "v w x y z") == []


def test_count_words():
    assert count_words("Hallo Welt, wie geht's?") == 4
    assert count_words("") == 0
