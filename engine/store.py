"""SQLite persistence: transcripts, dictionary, snippets and stats queries."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .textproc import Correction, Snippet

SCHEMA = """
CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    raw_text TEXT NOT NULL,
    text TEXT NOT NULL,
    words INTEGER NOT NULL,
    duration_s REAL NOT NULL,
    process_ms INTEGER NOT NULL DEFAULT 0,
    app TEXT NOT NULL DEFAULT '',
    window_title TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'other',
    language TEXT NOT NULL DEFAULT '',
    audio_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_transcripts_created ON transcripts(created_at);
CREATE TABLE IF NOT EXISTS dictionary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL,
    replacement TEXT,
    auto_learned INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    UNIQUE(word COLLATE NOCASE)
);
CREATE TABLE IF NOT EXISTS snippets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger TEXT NOT NULL UNIQUE COLLATE NOCASE,
    expansion TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    started_at REAL NOT NULL,
    ended_at REAL,
    status TEXT NOT NULL DEFAULT 'recording',  -- recording | processing | done | interrupted | error
    notes TEXT NOT NULL DEFAULT '',
    summary TEXT,
    action_items TEXT,
    language TEXT NOT NULL DEFAULT '',
    audio_path TEXT,
    source TEXT NOT NULL DEFAULT '',           -- both | desktop | mic | import; '' = older mic-only sessions
    terms TEXT NOT NULL DEFAULT ''             -- technical terms for this session, comma separated
);
CREATE TABLE IF NOT EXISTS session_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    speaker TEXT NOT NULL DEFAULT 'you',       -- you | them | system (notes like a reconnect)
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_session ON session_segments(session_id, start_s);
"""

MAX_PAGE = 500
SEGMENT_SPEAKER_MIGRATION = "ALTER TABLE session_segments ADD COLUMN speaker TEXT NOT NULL DEFAULT 'you'"  # older sessions had one speaker
SESSION_MIGRATIONS = (
    "ALTER TABLE sessions ADD COLUMN source TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE sessions ADD COLUMN terms TEXT NOT NULL DEFAULT ''",
)
MIGRATIONS = (
    "ALTER TABLE transcripts ADD COLUMN fixes_words INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE transcripts ADD COLUMN fixes_dict INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE transcripts ADD COLUMN auto_text TEXT",
)


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            columns = {r[1] for r in self._db.execute("PRAGMA table_info(transcripts)")}
            for sql in MIGRATIONS:
                if sql.split("ADD COLUMN ")[1].split()[0] not in columns:
                    self._db.execute(sql)
            segment_columns = {r[1] for r in self._db.execute("PRAGMA table_info(session_segments)")}
            if "speaker" not in segment_columns:
                self._db.execute(SEGMENT_SPEAKER_MIGRATION)
            session_columns = {r[1] for r in self._db.execute("PRAGMA table_info(sessions)")}
            for sql in SESSION_MIGRATIONS:
                if sql.split("ADD COLUMN ")[1].split()[0] not in session_columns:
                    self._db.execute(sql)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, params).fetchall()]

    def _write(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            cur = self._db.execute(sql, params)
            self._db.commit()
            return cur.lastrowid or cur.rowcount

    # --- transcripts -------------------------------------------------------
    def add_transcript(self, item: dict[str, Any]) -> dict[str, Any]:
        new_id = self._write(
            "INSERT INTO transcripts (created_at, raw_text, text, words, duration_s, process_ms, app,"
            " window_title, category, language, audio_path, fixes_words, fixes_dict)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item.get("created_at", time.time()), item["raw_text"], item["text"], item["words"],
                item["duration_s"], item.get("process_ms", 0), item.get("app", ""),
                item.get("window_title", ""), item.get("category", "other"),
                item.get("language", ""), item.get("audio_path"),
                item.get("fixes_words", 0), item.get("fixes_dict", 0),
            ),
        )
        return self.get_transcript(new_id)

    def get_transcript(self, transcript_id: int) -> dict[str, Any]:
        rows = self._query("SELECT * FROM transcripts WHERE id=?", (transcript_id,))
        if not rows:
            raise KeyError(f"Transkript {transcript_id} nicht gefunden")
        return rows[0]

    def list_transcripts(self, limit: int = 50, offset: int = 0, query: str = "") -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), MAX_PAGE))
        if query:
            return self._query(
                "SELECT * FROM transcripts WHERE text LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (f"%{query}%", limit, int(offset)),
            )
        return self._query(
            "SELECT * FROM transcripts ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, int(offset))
        )

    def update_transcript_text(self, transcript_id: int, text: str, words: int) -> dict[str, Any]:
        # auto_text keeps Murmel's own output from before the first edit, so later edits still compare against it
        self._write(
            "UPDATE transcripts SET auto_text=COALESCE(auto_text, text), text=?, words=? WHERE id=?",
            (text, words, transcript_id),
        )
        return self.get_transcript(transcript_id)

    def style_edits(self, category: str, limit: int = 50) -> list[dict[str, Any]]:
        """Edited transcripts of one category, newest first, for learning the user's writing style."""
        return self._query(
            "SELECT raw_text, auto_text, text FROM transcripts"
            " WHERE category=? AND auto_text IS NOT NULL AND auto_text != text"
            " ORDER BY created_at DESC LIMIT ?",
            (category, limit),
        )

    def delete_transcript(self, transcript_id: int) -> str | None:
        item = self.get_transcript(transcript_id)
        self._write("DELETE FROM transcripts WHERE id=?", (transcript_id,))
        return item.get("audio_path")

    def audio_paths_beyond(self, keep: int) -> list[tuple[int, str]]:
        rows = self._query(
            "SELECT id, audio_path FROM transcripts WHERE audio_path IS NOT NULL ORDER BY created_at DESC"
            " LIMIT -1 OFFSET ?",
            (keep,),
        )
        return [(r["id"], r["audio_path"]) for r in rows]

    def clear_audio_path(self, transcript_id: int) -> None:
        self._write("UPDATE transcripts SET audio_path=NULL WHERE id=?", (transcript_id,))

    # --- sessions (long recordings) ---------------------------------------
    def create_session(
        self, title: str, started_at: float, language: str, source: str = "", terms: str = "",
        status: str = "recording",
    ) -> dict[str, Any]:
        new_id = self._write(
            "INSERT INTO sessions (title, started_at, language, source, terms, status) VALUES (?,?,?,?,?,?)",
            (title, started_at, language, source, terms, status),
        )
        return self.get_session(new_id)

    def get_session(self, session_id: int) -> dict[str, Any]:
        rows = self._query("SELECT * FROM sessions WHERE id=?", (session_id,))
        if not rows:
            raise KeyError(f"Sitzung {session_id} nicht gefunden")
        return _decode_session(rows[0])

    def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), MAX_PAGE))
        rows = self._query(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ? OFFSET ?", (limit, int(offset))
        )
        return [_decode_session(r) for r in rows]

    def add_session_segment(
        self, session_id: int, start_s: float, end_s: float, text: str, speaker: str = "you"
    ) -> dict[str, Any]:
        new_id = self._write(
            "INSERT INTO session_segments (session_id, speaker, start_s, end_s, text) VALUES (?,?,?,?,?)",
            (session_id, speaker, start_s, end_s, text),
        )
        return self._query("SELECT * FROM session_segments WHERE id=?", (new_id,))[0]

    def session_segments(self, session_id: int) -> list[dict[str, Any]]:
        return self._query(
            "SELECT * FROM session_segments WHERE session_id=? ORDER BY start_s", (session_id,)
        )

    def replace_session_segments(self, session_id: int, rows: list[tuple[str, float, float, str]]) -> None:
        """Swap the whole transcript in one transaction, so a failed re-run never leaves half a transcript."""
        with self._lock:
            with self._db:
                self._db.execute("DELETE FROM session_segments WHERE session_id=?", (session_id,))
                self._db.executemany(
                    "INSERT INTO session_segments (session_id, speaker, start_s, end_s, text) VALUES (?,?,?,?,?)",
                    [(session_id, speaker, start, end, text) for speaker, start, end, text in rows],
                )

    def update_session_title(self, session_id: int, title: str) -> None:
        self._write("UPDATE sessions SET title=? WHERE id=?", (title, session_id))

    def set_session_ended(self, session_id: int, ended_at: float) -> None:
        self._write("UPDATE sessions SET ended_at=? WHERE id=?", (ended_at, session_id))

    def finish_session(self, session_id: int, ended_at: float, status: str) -> None:
        self._write("UPDATE sessions SET ended_at=?, status=? WHERE id=?", (ended_at, status, session_id))

    def set_session_status(self, session_id: int, status: str) -> None:
        self._write("UPDATE sessions SET status=? WHERE id=?", (status, session_id))

    def update_session_notes(self, session_id: int, notes: str) -> None:
        self._write("UPDATE sessions SET notes=? WHERE id=?", (notes, session_id))

    def set_session_summary(self, session_id: int, summary: str | None, action_items: list[str] | None) -> None:
        self._write(
            "UPDATE sessions SET summary=?, action_items=? WHERE id=?",
            (summary, json.dumps(action_items, ensure_ascii=False) if action_items is not None else None, session_id),
        )

    def set_session_audio(self, session_id: int, audio_path: str) -> None:
        self._write("UPDATE sessions SET audio_path=? WHERE id=?", (audio_path, session_id))

    def delete_session(self, session_id: int) -> str | None:
        session = self.get_session(session_id)
        self._write("DELETE FROM session_segments WHERE session_id=?", (session_id,))
        self._write("DELETE FROM sessions WHERE id=?", (session_id,))
        return session.get("audio_path")

    def mark_interrupted_sessions(self) -> int:
        """Sessions still marked as recording when the engine starts were cut off by a crash or shutdown.

        Their transcript is kept up to the cut, so they are 'interrupted', not failed. A re-run that was cut off
        never replaced the old transcript, so those sessions are simply done."""
        with self._lock:
            cur = self._db.execute(
                "UPDATE sessions SET status='interrupted', ended_at=COALESCE(ended_at, ?) WHERE status='recording'",
                (time.time(),),
            )
            self._db.execute("UPDATE sessions SET status='done' WHERE status='processing'")
            self._db.commit()
            return cur.rowcount

    def session_audio_paths_beyond(self, keep: int) -> list[tuple[int, str]]:
        rows = self._query(
            "SELECT id, audio_path FROM sessions WHERE audio_path IS NOT NULL ORDER BY started_at DESC"
            " LIMIT -1 OFFSET ?",
            (keep,),
        )
        return [(r["id"], r["audio_path"]) for r in rows]

    def clear_session_audio_path(self, session_id: int) -> None:
        self._write("UPDATE sessions SET audio_path=NULL WHERE id=?", (session_id,))

    # --- dictionary --------------------------------------------------------
    def list_dictionary(self) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM dictionary ORDER BY created_at DESC")

    def upsert_dictionary(self, word: str, replacement: str | None = None, auto: bool = False) -> dict[str, Any]:
        word = word.strip()
        replacement = (replacement or "").strip() or None
        if not word:
            raise ValueError("Wort darf nicht leer sein")
        self._write(
            "INSERT INTO dictionary (word, replacement, auto_learned, created_at) VALUES (?,?,?,?)"
            " ON CONFLICT(word) DO UPDATE SET replacement=excluded.replacement,"
            " auto_learned=excluded.auto_learned",
            (word, replacement, int(auto), time.time()),
        )
        return self._query("SELECT * FROM dictionary WHERE word=? COLLATE NOCASE", (word,))[0]

    def delete_dictionary(self, entry_id: int) -> None:
        self._write("DELETE FROM dictionary WHERE id=?", (entry_id,))

    def corrections(self) -> list[Correction]:
        return [Correction(r["word"], r["replacement"]) for r in self.list_dictionary() if r["replacement"]]

    def dictionary_suggestions(self, limit: int = 4) -> list[str]:
        """Unusual tokens from the history (acronyms, CamelCase, letter+digit) not yet in the dictionary."""
        known = {r["word"].lower() for r in self.list_dictionary()} | {
            (r["replacement"] or "").lower() for r in self.list_dictionary()
        }
        counts: dict[str, int] = {}
        for r in self._query("SELECT text FROM transcripts ORDER BY created_at DESC LIMIT 400"):
            for token in re.findall(r"\b(?:[A-ZÄÖÜ]{2,6}|[A-Za-z]+[a-z][A-Z]\w*|[A-Za-z]+\d+\w*)\b", r["text"]):
                if token.lower() not in known:
                    counts[token] = counts.get(token, 0) + 1
        return [t for t, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:limit]]

    def vocabulary(self) -> list[str]:
        """Words Whisper should know: plain entries plus correction targets."""
        words = [r["replacement"] or r["word"] for r in self.list_dictionary()]
        return list(dict.fromkeys(words))

    # --- snippets ----------------------------------------------------------
    def list_snippets(self) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM snippets ORDER BY created_at DESC")

    def upsert_snippet(self, trigger: str, expansion: str, snippet_id: int | None = None) -> dict[str, Any]:
        trigger, expansion = trigger.strip(), expansion.strip()
        if not trigger or not expansion:
            raise ValueError("Auslöser und Text dürfen nicht leer sein")
        if snippet_id:
            self._write("UPDATE snippets SET trigger=?, expansion=? WHERE id=?", (trigger, expansion, snippet_id))
        else:
            self._write(
                "INSERT INTO snippets (trigger, expansion, created_at) VALUES (?,?,?)"
                " ON CONFLICT(trigger) DO UPDATE SET expansion=excluded.expansion",
                (trigger, expansion, time.time()),
            )
        return self._query("SELECT * FROM snippets WHERE trigger=? COLLATE NOCASE", (trigger,))[0]

    def delete_snippet(self, snippet_id: int) -> None:
        self._write("DELETE FROM snippets WHERE id=?", (snippet_id,))

    def snippets(self) -> list[Snippet]:
        return [Snippet(r["trigger"], r["expansion"]) for r in self.list_snippets()]

    # --- stats -------------------------------------------------------------
    def stats(self, days: int | None, typing_wpm: int, today: date | None = None) -> dict[str, Any]:
        today = today or date.today()
        since = (
            datetime.combine(today - timedelta(days=days - 1), datetime.min.time()).timestamp() if days else 0
        )
        rows = self.analysis_rows(since)
        all_days = {
            date.fromtimestamp(r["created_at"])
            for r in self._query("SELECT created_at FROM transcripts")
        }
        summary = summarize(rows, all_days, days, typing_wpm, today)
        summary["fixes_words"] = sum(r["fixes_words"] for r in rows)
        summary["fixes_dict"] = sum(r["fixes_dict"] for r in rows)
        return summary

    def analysis_rows(self, since: float = 0) -> list[dict[str, Any]]:
        return self._query(
            "SELECT created_at, text, words, duration_s, app, window_title, category, fixes_words, fixes_dict"
            " FROM transcripts WHERE created_at >= ?",
            (since,),
        )

    def daily_activity(self, days: int, today: date | None = None) -> list[dict[str, Any]]:
        """Words per day for the streak heatmap, oldest first."""
        today = today or date.today()
        start = today - timedelta(days=days - 1)
        counts: dict[str, int] = {}
        since = datetime.combine(start, datetime.min.time()).timestamp()
        for r in self._query("SELECT created_at, words FROM transcripts WHERE created_at >= ?", (since,)):
            key = date.fromtimestamp(r["created_at"]).isoformat()
            counts[key] = counts.get(key, 0) + r["words"]
        return [
            {"date": (start + timedelta(days=i)).isoformat(), "words": counts.get((start + timedelta(days=i)).isoformat(), 0)}
            for i in range(days)
        ]


def _decode_session(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("action_items")
    return {**row, "action_items": json.loads(raw) if raw else None}


def summarize(
    rows: list[dict[str, Any]], active_days: set[date], days: int | None, typing_wpm: int, today: date
) -> dict[str, Any]:
    words = sum(r["words"] for r in rows)
    seconds = sum(r["duration_s"] for r in rows)
    wpm = round(words / (seconds / 60)) if seconds > 0 else 0
    typing_minutes = words / max(typing_wpm, 1)
    saved_minutes = max(0.0, typing_minutes - seconds / 60)

    span = days or max(1, (today - min((date.fromtimestamp(r["created_at"]) for r in rows), default=today)).days + 1)
    daily: dict[str, dict[str, float]] = {}
    for offset in range(span - 1, -1, -1):
        daily[(today - timedelta(days=offset)).isoformat()] = {"words": 0, "seconds": 0.0, "sessions": 0}
    hours = [0] * 24
    apps: dict[str, int] = {}
    for r in rows:
        stamp = datetime.fromtimestamp(r["created_at"])
        bucket = daily.get(stamp.date().isoformat())
        if bucket is not None:
            bucket["words"] += r["words"]
            bucket["seconds"] += r["duration_s"]
            bucket["sessions"] += 1
        hours[stamp.hour] += r["words"]
        app = (r["app"] or "Unbekannt").removesuffix(".exe")
        apps[app] = apps.get(app, 0) + r["words"]

    current, longest = streaks(active_days, today)
    return {
        "words": words,
        "sessions": len(rows),
        "seconds": round(seconds, 1),
        "wpm": wpm,
        "time_saved_min": round(saved_minutes, 1),
        "streak": current,
        "longest_streak": longest,
        "today_words": daily.get(today.isoformat(), {}).get("words", 0),
        "daily": [
            {"date": d, "words": v["words"], "sessions": v["sessions"],
             "wpm": round(v["words"] / (v["seconds"] / 60)) if v["seconds"] else 0}
            for d, v in daily.items()
        ],
        "hours": hours,
        "apps": sorted(({"app": k, "words": v} for k, v in apps.items()), key=lambda a: -a["words"])[:8],
    }


def streaks(active_days: set[date], today: date) -> tuple[int, int]:
    current = 0
    cursor = today if today in active_days else today - timedelta(days=1)
    while cursor in active_days:
        current += 1
        cursor -= timedelta(days=1)
    longest = run = 0
    previous: date | None = None
    for d in sorted(active_days):
        run = run + 1 if previous and d - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = d
    return current, longest
