"""Voice profile and usage analytics computed from transcript rows."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any

VOICE_UNLOCK_WORDS = 2000
TOP_WORDS = 12
MIN_PHRASE_COUNT = 2
USAGE_BUCKETS = ("ai", "other", "personal", "email", "work", "documents")
AI_APPS = ("chatgpt", "claude", "copilot", "gemini", "perplexity", "cursor", "windsurf", "lm studio", "codex")
DOC_APPS = ("winword", "word", "notion", "obsidian", "notepad", "google docs", "onenote", "goodnotes", "pages")
WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")

STOPWORDS = set("""
der die das den dem des ein eine einer eines einem einen und oder aber auch noch nur schon so wie was wer wo
ich du er sie es wir ihr mich mir dich dir sich uns euch mein meine dein deine sein seine ihre unser
ist bin bist sind war waren wird werden wurde hat habe hast haben hatte kann kannst können muss müssen soll
will wollen mal ja nein nicht kein keine keinen zu zum zur im in am an auf aus bei mit nach von vor für über
unter um bis als dass ob wenn dann denn weil also doch da hier jetzt man mehr sehr ganz gut halt eben einfach
the a an and or but to of in on at for with is are was were be been it this that i you he she we they my your
so just like really do does did have has had not no yes can could would should will what when where how
""".split())


def usage_bucket(app: str, title: str, category: str) -> str:
    if category in ("personal", "email", "work"):
        return category
    hay = f"{app} {title}".lower()
    if any(k in hay for k in AI_APPS):
        return "ai"
    if any(k in hay for k in DOC_APPS):
        return "documents"
    return "other"


def usage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(usage_bucket(r["app"] or "", r.get("window_title") or "", r["category"]) for r in rows)
    total = sum(counts.values())
    apps = {(r["app"] or "").lower() for r in rows if r["app"]}
    return {
        "total_apps": len(apps),
        "buckets": [
            {"key": k, "count": counts.get(k, 0), "pct": round(counts.get(k, 0) / total * 100) if total else 0}
            for k in USAGE_BUCKETS
        ],
    }


def _words(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß][\wÄÖÜäöüß'-]*", text)]


def voice_profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(r["words"] for r in rows)
    base = {"unlocked": total >= VOICE_UNLOCK_WORDS, "words_total": total, "unlock_at": VOICE_UNLOCK_WORDS,
            "remaining": max(0, VOICE_UNLOCK_WORDS - total)}
    if not base["unlocked"]:
        return base

    all_words: list[str] = []
    phrases: Counter[str] = Counter()
    hours: Counter[int] = Counter()
    weekdays: Counter[int] = Counter()
    apps: Counter[str] = Counter()
    for r in rows:
        words = _words(r["text"])
        all_words.extend(words)
        for n in (3, 2):
            for i in range(len(words) - n + 1):
                gram = words[i:i + n]
                if sum(w not in STOPWORDS for w in gram) >= 2:
                    phrases[" ".join(gram)] += 1
        stamp = datetime.fromtimestamp(r["created_at"])
        hours[stamp.hour] += r["words"]
        weekdays[stamp.weekday()] += r["words"]
        if r["app"]:
            apps[r["app"].removesuffix(".exe").removesuffix(".EXE")] += r["words"]

    content = Counter(w for w in all_words if w not in STOPWORDS and len(w) >= 3)
    catch = next((p for p, c in phrases.most_common(40) if c >= MIN_PHRASE_COUNT and len(p.split()) >= 2), None)
    peak_hour = hours.most_common(1)[0][0] if hours else 0
    seconds = sum(r["duration_s"] for r in rows)
    wpm = round(total / (seconds / 60)) if seconds else 0
    avg_len = round(total / len(rows)) if rows else 0
    richness = round(len(set(all_words)) / len(all_words) * 100) if all_words else 0
    return {
        **base,
        "most_used_word": content.most_common(1)[0][0] if content else None,
        "most_used_count": content.most_common(1)[0][1] if content else 0,
        "catch_phrase": catch,
        "catch_phrase_count": phrases[catch] if catch else 0,
        "peak_hour": peak_hour,
        "peak_weekday": WEEKDAYS[weekdays.most_common(1)[0][0]] if weekdays else None,
        "favorite_app": apps.most_common(1)[0][0] if apps else None,
        "avg_words": avg_len,
        "longest": max((r["words"] for r in rows), default=0),
        "richness": richness,
        "wpm": wpm,
        "top_words": [{"word": w, "count": c} for w, c in content.most_common(TOP_WORDS)],
        "persona": persona(wpm, peak_hour, avg_len, richness),
    }


def persona(wpm: int, peak_hour: int, avg_len: int, richness: int) -> dict[str, str]:
    if wpm >= 170:
        return {"title": "Der Schnellsprecher", "text": "Deine Gedanken kommen schneller, als jede Tastatur mithalten könnte."}
    if peak_hour >= 21 or peak_hour < 4:
        return {"title": "Die Nachteule", "text": "Wenn andere schlafen, sprichst du deine besten Ideen ein."}
    if peak_hour < 9:
        return {"title": "Der Frühaufsteher", "text": "Du erledigst das Wichtigste, bevor der Tag richtig beginnt."}
    if avg_len >= 60:
        return {"title": "Der Erzähler", "text": "Du denkst in ganzen Absätzen – ausführlich und mit Kontext."}
    if richness >= 60:
        return {"title": "Der Wortkünstler", "text": "Dein Wortschatz ist abwechslungsreich und präzise."}
    return {"title": "Der Macher", "text": "Kurz, klar, auf den Punkt – du diktierst, um Dinge zu erledigen."}
