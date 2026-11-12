"""Session export as Markdown or plain text, for notes apps and AI tools."""
from __future__ import annotations

import re
import time
from typing import Any

SPEAKER = {"you": "Du", "them": "Gegenüber", "system": "Hinweis"}
SOURCE = {"both": "Mikrofon + Desktop-Audio", "desktop": "Desktop-Audio", "mic": "Mikrofon", "import": "Importierte Datei"}
MERGE_GAP_S = 3.0  # segments of one speaker closer than this become one paragraph
PARAGRAPH_MAX_S = 90.0  # a new paragraph (and timestamp) at least this often, so long monologues stay navigable


def clock(seconds: float) -> str:
    total = int(seconds)
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def paragraphs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Consecutive segments of the same speaker merged into readable paragraphs."""
    out: list[dict[str, Any]] = []
    for seg in sorted(segments, key=lambda s: s["start_s"]):
        text = seg["text"].strip()
        if not text:
            continue
        last = out[-1] if out else None
        if (
            last and last["speaker"] == seg["speaker"] != "system"
            and seg["start_s"] - last["end_s"] <= MERGE_GAP_S
            and seg["end_s"] - last["start_s"] <= PARAGRAPH_MAX_S
        ):
            last["text"] = f"{last['text']} {text}"
            last["end_s"] = seg["end_s"]
        else:
            out.append({"speaker": seg["speaker"], "start_s": seg["start_s"], "end_s": seg["end_s"], "text": text})
    return out


def _duration(session: dict[str, Any], segments: list[dict[str, Any]]) -> float:
    if session.get("ended_at") and session.get("started_at"):
        return max(0.0, session["ended_at"] - session["started_at"])
    return max((s["end_s"] for s in segments), default=0.0)


def _speakers(paras: list[dict[str, Any]]) -> set[str]:
    return {p["speaker"] for p in paras if p["speaker"] != "system"}


def to_markdown(session: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    paras = paragraphs(segments)
    title = session.get("title") or "Sitzung"
    started = time.strftime("%d.%m.%Y, %H:%M", time.localtime(session["started_at"]))
    words = sum(len(p["text"].split()) for p in paras if p["speaker"] != "system")
    meta = [started, f"Dauer {clock(_duration(session, segments))}", f"{words} Wörter"]
    if session.get("source") in SOURCE:
        meta.append(SOURCE[session["source"]])
    lines = [f"# {title}", "", "*" + " · ".join(meta) + "*", ""]
    if session.get("terms"):
        lines += [f"**Fachbegriffe:** {session['terms']}", ""]
    lines += ["## Transkript", ""]
    named = len(_speakers(paras)) > 1
    for p in paras:
        if p["speaker"] == "system":
            lines += [f"> *[{clock(p['start_s'])}] {p['text']}*", ""]
            continue
        label = f"**{SPEAKER.get(p['speaker'], p['speaker'])}** " if named else ""
        lines += [f"{label}`[{clock(p['start_s'])}]` {p['text']}", ""]
    notes = (session.get("notes") or "").strip()
    if notes:
        lines += ["## Notizen", "", notes, ""]
    return "\n".join(lines).rstrip() + "\n"


def to_text(session: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    """Plain paragraphs without timestamps, ready to paste into a prompt."""
    paras = paragraphs([s for s in segments if s["speaker"] != "system"])
    named = len(_speakers(paras)) > 1
    lines = [session.get("title") or "Sitzung", ""]
    for p in paras:
        prefix = f"{SPEAKER.get(p['speaker'], p['speaker'])}: " if named else ""
        lines += [prefix + p["text"], ""]
    return "\n".join(lines).rstrip() + "\n"


def filename(session: dict[str, Any], extension: str) -> str:
    day = time.strftime("%Y-%m-%d", time.localtime(session["started_at"]))
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", session.get("title") or "Sitzung").strip(" .") or "Sitzung"
    return f"{day} {title[:80]}.{extension}"
