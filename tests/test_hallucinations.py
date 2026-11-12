from types import SimpleNamespace

from engine import textproc
from engine.stt import is_unreliable


def test_known_subtitle_credits_are_removed_anywhere():
    text = "Der Eigenwert ist null. Untertitel im Auftrag des ZDF für funk, 2017"
    assert textproc.strip_hallucinations(text) == "Der Eigenwert ist null."


def test_closing_phrase_alone_is_dropped():
    assert textproc.strip_hallucinations("Vielen Dank fürs Zuschauen!") == ""
    assert textproc.strip_hallucinations(" Thank you. ") == ""


def test_closing_phrase_inside_real_speech_stays():
    text = "Danke, dass Sie heute wieder dabei sind, wir machen mit Matrizen weiter."
    assert textproc.strip_hallucinations(text) == text


def test_repetition_loop_is_collapsed():
    looped = "und dann und dann und dann und dann gehen wir weiter"
    assert textproc.strip_hallucinations(looped) == "und dann gehen wir weiter"


def test_normal_repetition_of_two_is_kept():
    text = "ja ja, genau so"
    assert textproc.strip_hallucinations(text) == text


def test_whisper_signals_mark_unreliable_segments():
    assert is_unreliable(SimpleNamespace(no_speech_prob=0.9, avg_logprob=-1.5, compression_ratio=1.2))
    assert is_unreliable(SimpleNamespace(no_speech_prob=0.0, avg_logprob=-0.2, compression_ratio=3.1))
    assert not is_unreliable(SimpleNamespace(no_speech_prob=0.9, avg_logprob=-0.3, compression_ratio=1.2))
    assert not is_unreliable(SimpleNamespace(no_speech_prob=0.1, avg_logprob=-0.4, compression_ratio=1.5))
