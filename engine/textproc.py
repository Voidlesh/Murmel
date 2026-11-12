"""Pure text pipeline: fillers, voice commands, style rules, dictionary, snippets, learning."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

# "um" is deliberately absent: it is a real German word ("um 3 Uhr").
FILLERS = ("ähm", "äh", "öhm", "öh", "ehm", "hmm", "hm", "uhm", "uh", "erm")
_FILLER_RE = re.compile(r",?\s*\b(?:" + "|".join(FILLERS) + r")\b\s*,?", re.IGNORECASE)

VOICE_COMMANDS = (
    (re.compile(r"[,.]?\s*\b(?:neuer absatz|new paragraph)\b[,.]?\s*", re.I), "\n\n"),
    (re.compile(r"[,.]?\s*\b(?:neue zeile|new line)\b[,.]?\s*", re.I), "\n"),
)

TONES = ("formal", "casual", "very_casual")

# Text Whisper invents on silence, music or noise (it learned it from subtitled videos).
# Removed wherever it appears: never said in a lecture or a meeting.
_HALLUCINATION_ANYWHERE = re.compile(
    r"(?:Untertitel(?:ung)?\s+(?:im\s+Auftrag\s+)?(?:des|der|von|für|durch)\s+[^.!?]*(?:ZDF|ARD|WDR|SWR|NDR|BR|funk|Amara)[^.!?]*[.!?]?"
    r"|Untertitel\s+(?:von|im Auftrag)[^.!?]*[.!?]?"
    r"|Copyright\s+(?:WDR|SWR|ZDF|ARD|NDR)\s*\d{0,4}[.!?]?"
    r"|(?:Subtitles|Captions)\s+by\s+[^.!?]*[.!?]?"
    r"|\bAmara\.org\b[^.!?]*[.!?]?)",
    re.IGNORECASE,
)
# Removed only when they are the whole segment: in running speech they may be real.
_HALLUCINATION_ALONE = re.compile(
    r"^\W*(?:(?:vielen\s+)?dank\s+(?:fürs|für\s+das|für's)\s+zu(?:schauen|sehen|hören)"
    r"|bis\s+zum\s+nächsten\s+mal|tschüss|danke|vielen\s+dank|amen"
    r"|thank\s+you(?:\s+for\s+watching)?|thanks\s+for\s+watching|please\s+subscribe|bye"
    r"|musik|music|applaus|applause|\.\.\.)\W*$",
    re.IGNORECASE,
)
_REPEAT_RE = re.compile(r"\b((?:[\w'äöüÄÖÜß-]+[\s,]+){0,7}?[\w'äöüÄÖÜß-]+)(?:[\s,.!?]+\1\b){2,}", re.IGNORECASE)

MAX_LEARN_SPAN = 3


@dataclass(frozen=True)
class Correction:
    wrong: str
    right: str


@dataclass(frozen=True)
class Snippet:
    trigger: str
    expansion: str


def remove_fillers(text: str) -> str:
    cleaned = _FILLER_RE.sub(" ", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
    cleaned = re.sub(r",([.!?])", r"\1", cleaned)
    cleaned = re.sub(r"^[,.\s]+", "", cleaned).strip()
    return _capitalize_first(cleaned) if text[:1].isupper() else cleaned


def strip_hallucinations(text: str) -> str:
    """Drop typical Whisper inventions and collapse loops ("und dann und dann und dann ...")."""
    cleaned = _HALLUCINATION_ANYWHERE.sub(" ", text)
    cleaned = _REPEAT_RE.sub(r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if _HALLUCINATION_ALONE.match(cleaned):
        return ""
    return cleaned


def apply_voice_commands(text: str) -> str:
    for pattern, replacement in VOICE_COMMANDS:
        text = pattern.sub(replacement, text)
    lines = [_capitalize_first(line.strip()) for line in text.split("\n")]
    return "\n".join(lines).strip()


def apply_style(text: str, tone: str) -> str:
    """Rule-based tone. formal keeps Whisper's punctuation; casual drops the
    final period; very_casual also lowercases sentence starts."""
    if tone not in TONES or not text:
        return text
    if tone == "formal":
        return _ensure_final_punctuation(_capitalize_first(text))
    stripped = re.sub(r"\.(?=\s*$)", "", text)
    if tone == "casual":
        return stripped
    return re.sub(r"(^|[.!?]\s+|\n)([A-ZÄÖÜ])(?=[a-zäöüß])", lambda m: m.group(1) + m.group(2).lower(), stripped)


def apply_corrections(text: str, corrections: list[Correction]) -> str:
    return apply_corrections_counted(text, corrections)[0]


def apply_corrections_counted(text: str, corrections: list[Correction]) -> tuple[str, int]:
    """Apply dictionary corrections and report how many replacements actually changed text."""
    fixes = 0
    for c in sorted(corrections, key=lambda c: len(c.wrong), reverse=True):
        if not c.wrong.strip():
            continue
        pattern = re.compile(r"(?<![\wäöüß])" + re.escape(c.wrong) + r"(?![\wäöüß])", re.IGNORECASE)
        text, n = pattern.subn(lambda m, r=c.right: r, text)
        fixes += n if c.wrong != c.right else 0
    return text, fixes


def count_changed_words(before: str, after: str) -> int:
    """Words that were removed or rewritten between two versions (case/punctuation ignored)."""
    a = [t.lower() for t in _tokens(before)]
    b = [t.lower() for t in _tokens(after)]
    changed = 0
    for op, i1, i2, _j1, _j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            changed += i2 - i1
    return changed


def apply_snippets(text: str, snippets: list[Snippet]) -> str:
    for s in sorted(snippets, key=lambda s: len(s.trigger), reverse=True):
        trigger = s.trigger.strip()
        if not trigger:
            continue
        whole = re.fullmatch(r"\s*" + re.escape(trigger) + r"[\s.!?,]*", text, re.IGNORECASE)
        if whole:
            return s.expansion
        # a sentence period right after a trailing snippet would corrupt e.g. an e-mail address
        pattern = re.compile(
            r"(?<![\wäöüß])" + re.escape(trigger) + r"(?![\wäöüß])(?:[.!?](?=\s*$))?", re.IGNORECASE
        )
        text = pattern.sub(lambda m, e=s.expansion: e, text)
    return text


def learn_corrections(original: str, edited: str) -> list[Correction]:
    """Diff two versions word by word and return small replacements as corrections."""
    a, b = _tokens(original), _tokens(edited)
    learned: list[Correction] = []
    matcher = difflib.SequenceMatcher(a=[t.lower() for t in a], b=[t.lower() for t in b], autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            # case-only change, e.g. "github" -> "GitHub"
            for x, y in zip(a[i1:i2], b[j1:j2]):
                if x != y and len(x) > 1:
                    learned.append(Correction(x, y))
            continue
        if op != "replace":
            continue
        if (i2 - i1) > MAX_LEARN_SPAN or (j2 - j1) > MAX_LEARN_SPAN:
            continue
        wrong, right = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if wrong and right and wrong.lower() != right.lower():
            learned.append(Correction(wrong, right))
    return _dedupe(learned)


def count_words(text: str) -> int:
    return len(re.findall(r"[\wäöüßÄÖÜ'-]+", text))


def _tokens(text: str) -> list[str]:
    return [t.strip(".,!?;:\"'()") for t in text.split() if t.strip(".,!?;:\"'()")]


def _dedupe(items: list[Correction]) -> list[Correction]:
    seen: set[tuple[str, str]] = set()
    out: list[Correction] = []
    for c in items:
        key = (c.wrong.lower(), c.right)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _capitalize_first(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _ensure_final_punctuation(text: str) -> str:
    stripped = text.rstrip()
    if not stripped or stripped[-1] in ".!?:;…)\"'" or "\n" in stripped[-2:]:
        return stripped
    return stripped + "."
