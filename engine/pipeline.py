"""Turns raw Whisper text into the final text for the target app."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from . import textproc
from .style import StyleContext, apply_final_period

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineResult:
    text: str
    polished_by_llm: bool
    fixes_words: int = 0
    fixes_dict: int = 0


def process(
    raw: str,
    category: str,
    settings: dict[str, Any],
    corrections: list[textproc.Correction],
    snippets: list[textproc.Snippet],
    vocabulary: list[str],
    polish: Callable[[str, str, dict[str, Any], list[str], StyleContext], str] | None = None,
    style: StyleContext | None = None,
) -> PipelineResult:
    style = style or StyleContext()
    tone = settings["style"].get(category, "formal")
    text = raw.strip()
    if settings.get("remove_fillers"):
        text = textproc.remove_fillers(text)
    if settings.get("voice_commands"):
        text = textproc.apply_voice_commands(text)

    polished = False
    if polish and settings["llm"].get("enabled") and textproc.count_words(text) >= 3:
        try:
            text = polish(text, tone, settings["llm"], vocabulary, style)
            polished = True
        except Exception:  # noqa: BLE001 - polish is best effort, rules still apply
            log.warning("KI-Polish fehlgeschlagen, nutze Regel-Ergebnis", exc_info=True)

    text = apply_final_period(textproc.apply_style(text, tone), style.final_period)
    fixes_words = textproc.count_changed_words(raw, text)
    text, fixes_dict = textproc.apply_corrections_counted(text, corrections)
    text = textproc.apply_snippets(text, snippets)
    return PipelineResult(text, polished, fixes_words, fixes_dict)
