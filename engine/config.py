"""Settings persisted as JSON in %APPDATA%/Murmel."""
from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("MURMEL_DATA_DIR") or Path(os.environ.get("APPDATA", Path.home())) / "Murmel")
AUDIO_DIR = DATA_DIR / "audio"
SETTINGS_PATH = DATA_DIR / "settings.json"

DEFAULTS: dict[str, Any] = {
    "user_name": "",
    "hotkey": "caps lock",
    "tap_for_hands_free": True,
    "language": "de",
    "model": "large-v3-turbo",
    "device": "auto",
    "beam_size": 1,
    "mic_device": None,
    "sounds": True,
    "duck_audio": True,
    "duck_level": 0.15,
    "restore_clipboard": True,
    "copy_fallback": True,
    "keep_audio": True,
    "session_hotkey": "",
    "session_keep_audio": True,
    "remove_fillers": True,
    "voice_commands": True,
    "typing_wpm": 40,
    "daily_goal": 1000,
    "insights_cards": ["words", "wpm", "time_saved", "streak", "sessions", "goal"],
    "llm": {
        "enabled": False,
        "base_url": "http://localhost:1234/v1",
        "model": "",
        "custom_instructions": "",
        "timeout_s": 10,
    },
    "style": {"personal": "casual", "work": "formal", "email": "formal", "other": "formal"},
    "style_apps": {
        "personal": ["discord.exe", "whatsapp.exe", "telegram.exe", "signal.exe", "WhatsApp", "Instagram"],
        "work": ["slack.exe", "ms-teams.exe", "teams.exe", "Slack", "Notion"],
        "email": ["outlook.exe", "olk.exe", "thunderbird.exe", "Gmail", "Outlook", "Mail"],
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(path: Path = SETTINGS_PATH) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return copy.deepcopy(DEFAULTS)
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.exception("settings.json unreadable, using defaults")
        return copy.deepcopy(DEFAULTS)
    return _merge(DEFAULTS, stored if isinstance(stored, dict) else {})


def save_settings(settings: dict[str, Any], path: Path = SETTINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def update_settings(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    unknown = set(patch) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"Unbekannte Einstellung(en): {', '.join(sorted(unknown))}")
    return _merge(current, patch)
