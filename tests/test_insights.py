from datetime import datetime

from engine.insights import VOICE_UNLOCK_WORDS, persona, usage, usage_bucket, voice_profile


def row(text, words, hour=10, app="code.exe", category="other", title="", duration=10.0):
    return {"text": text, "words": words, "duration_s": duration, "app": app, "category": category,
            "window_title": title, "created_at": datetime(2026, 11, 2, hour).timestamp()}


def test_usage_bucket_detection():
    assert usage_bucket("discord.exe", "", "personal") == "personal"
    assert usage_bucket("chrome.exe", "ChatGPT - Chrome", "other") == "ai"
    assert usage_bucket("WINWORD.EXE", "Bericht.docx", "other") == "documents"
    assert usage_bucket("explorer.exe", "", "other") == "other"


def test_usage_percentages():
    u = usage([row("a", 1, app="claude.exe"), row("b", 1, app="discord.exe", category="personal")])
    buckets = {b["key"]: b for b in u["buckets"]}
    assert buckets["ai"]["pct"] == 50 and buckets["personal"]["count"] == 1
    assert u["total_apps"] == 2


def test_voice_profile_locked_below_threshold():
    vp = voice_profile([row("hallo welt", 100)])
    assert vp["unlocked"] is False and vp["remaining"] == VOICE_UNLOCK_WORDS - 100


def test_voice_profile_unlocked_stats():
    rows = [row("Ehrlich gesagt finde ich das Projekt super spannend", 800, hour=22) for _ in range(3)]
    vp = voice_profile(rows)
    assert vp["unlocked"]
    assert vp["catch_phrase"] in {"ehrlich gesagt", "ehrlich gesagt finde", "projekt super", "projekt super spannend",
                                  "super spannend", "gesagt finde"}
    assert vp["most_used_word"] in {"ehrlich", "gesagt", "finde", "projekt", "super", "spannend"}
    assert vp["peak_hour"] == 22
    assert vp["persona"]["title"]


def test_persona_rules():
    assert persona(180, 12, 10, 10)["title"] == "Der Schnellsprecher"
    assert persona(120, 23, 10, 10)["title"] == "Die Nachteule"
    assert persona(120, 7, 10, 10)["title"] == "Der Frühaufsteher"
