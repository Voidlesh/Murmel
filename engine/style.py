"""Learns how the user wants their text written from the edits they make to history entries."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MIN_EDITS = 3
MIN_SHARE = 0.7
MAX_EXAMPLES = 3
MAX_EXAMPLE_CHARS = 400


@dataclass(frozen=True)
class Example:
    raw: str
    final: str


@dataclass(frozen=True)
class StyleContext:
    final_period: bool | None = None
    examples: tuple[Example, ...] = ()

    def rule_lines(self) -> list[str]:
        lines = []
        if self.final_period is True:
            lines.append("End the text with a period.")
        if self.final_period is False:
            lines.append("Do not put a period at the end of the text.")
        return lines


def build_context(rows: list[dict[str, Any]]) -> StyleContext:
    """rows: edited transcripts, newest first, with keys raw_text, auto_text (Murmel's output) and text (user's version)."""
    if not rows:
        return StyleContext()
    examples = tuple(
        Example(r["raw_text"], r["text"])
        for r in rows
        if len(r["raw_text"]) <= MAX_EXAMPLE_CHARS and len(r["text"]) <= MAX_EXAMPLE_CHARS
    )[:MAX_EXAMPLES]
    return StyleContext(final_period=_final_period_preference(rows), examples=examples)


def _ends_with_period(text: str) -> bool:
    return text.rstrip().endswith(".")


def _final_period_preference(rows: list[dict[str, Any]]) -> bool | None:
    removed = sum(1 for r in rows if _ends_with_period(r["auto_text"]) and not _ends_with_period(r["text"]))
    added = sum(1 for r in rows if not _ends_with_period(r["auto_text"]) and _ends_with_period(r["text"]))
    if removed >= MIN_EDITS and removed / len(rows) >= MIN_SHARE:
        return False
    if added >= MIN_EDITS and added / len(rows) >= MIN_SHARE:
        return True
    return None


def apply_final_period(text: str, want: bool | None) -> str:
    """Apply a learned end-of-text preference; None leaves the text as it is."""
    stripped = text.rstrip()
    if not stripped or want is None:
        return text
    if want is False:
        return stripped.removesuffix(".").rstrip() if stripped.endswith(".") else text
    return stripped if stripped.endswith((".", "!", "?", ":", ";", "…")) else stripped + "."
