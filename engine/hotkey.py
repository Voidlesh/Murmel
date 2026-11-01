"""Global push-to-talk hotkey.

Hold the hotkey -> record until release. Tap it quickly -> hands-free mode,
tap again to finish. Esc cancels. A single-key hotkey (e.g. Caps Lock) is
suppressed so it does not toggle its normal function.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import keyboard

log = logging.getLogger(__name__)

TAP_MAX_S = 0.3


def validate_hotkey(hotkey: str) -> list[str]:
    """Key names of a combo such as 'ctrl+windows'; raises ValueError for empty or unknown keys."""
    keys = [k.strip().lower() for k in hotkey.split("+") if k.strip()]
    if not keys:
        raise ValueError("Hotkey darf nicht leer sein")
    for k in keys:
        keyboard.key_to_scan_codes(k)  # raises ValueError for unknown names
    return keys


class HotkeyController:
    def __init__(
        self,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_cancel: Callable[[], None],
        on_hands_free: Callable[[], None],
    ) -> None:
        self._on_start, self._on_stop = on_start, on_stop
        self._on_cancel, self._on_hands_free = on_cancel, on_hands_free
        self._keys: list[str] = []
        self._held: set[str] = set()
        self._combo_down = False
        self._pressed_at = 0.0
        self._hands_free = False
        self._recording = False
        self._tap_enabled = True
        self._hooks: list = []
        self._lock = threading.Lock()

    def configure(self, hotkey: str, tap_for_hands_free: bool) -> None:
        keys = validate_hotkey(hotkey)
        self.unhook()
        self._keys, self._tap_enabled = keys, tap_for_hands_free
        if len(keys) == 1:
            self._hooks.append(keyboard.hook_key(keys[0], self._single_key_event, suppress=True))
        else:
            self._hooks.append(keyboard.hook(self._combo_event))
        self._hooks.append(keyboard.on_press_key("esc", lambda _e: self._escape(), suppress=False))
        log.info("Hotkey aktiv: %s", hotkey)

    def unhook(self) -> None:
        for hook in self._hooks:
            try:
                keyboard.unhook(hook)
            except (KeyError, ValueError):
                pass
        self._hooks = []

    def set_recording(self, recording: bool) -> None:
        """Keep in sync when recording is started/stopped from the UI."""
        with self._lock:
            self._recording = recording
            if not recording:
                self._hands_free = False

    def toggle_from_ui(self) -> None:
        with self._lock:
            if self._recording:
                self._recording = self._hands_free = False
                stop = True
            else:
                self._recording = self._hands_free = True
                stop = False
        (self._on_stop if stop else self._start_hands_free)()

    def _start_hands_free(self) -> None:
        self._on_start()
        self._on_hands_free()

    def _single_key_event(self, event: keyboard.KeyboardEvent) -> bool:
        if event.event_type == keyboard.KEY_DOWN:
            self._down()
        else:
            self._up()
        return False  # blocking hooks only swallow the key when the callback returns False

    def _combo_event(self, event: keyboard.KeyboardEvent) -> None:
        name = (event.name or "").lower()
        names = {name}
        if event.event_type == keyboard.KEY_DOWN:
            self._held |= names
            if not self._combo_down and all(self._matches(k) for k in self._keys):
                self._combo_down = True
                self._down()
        else:
            self._held -= names
            if self._combo_down and not all(self._matches(k) for k in self._keys):
                self._combo_down = False
                self._up()

    def _matches(self, key: str) -> bool:
        aliases = {"win": {"windows", "left windows", "right windows"}, "windows": {"left windows", "right windows"},
                   "ctrl": {"left ctrl", "right ctrl"}, "alt": {"left alt", "right alt", "alt gr"},
                   "shift": {"left shift", "right shift"}}
        return key in self._held or bool(aliases.get(key, set()) & self._held)

    def _down(self) -> None:
        with self._lock:
            if self._pressed_at:  # key repeat
                return
            self._pressed_at = time.monotonic()
            if self._recording and self._hands_free:
                action = "stop"
                self._recording = self._hands_free = False
            elif not self._recording:
                action = "start"
                self._recording = True
            else:
                action = None
        if action == "start":
            self._on_start()
        elif action == "stop":
            self._on_stop()

    def _up(self) -> None:
        with self._lock:
            held_for = time.monotonic() - self._pressed_at if self._pressed_at else 0
            self._pressed_at = 0.0
            if not self._recording or self._hands_free:
                return
            if self._tap_enabled and held_for < TAP_MAX_S:
                self._hands_free = True
                action = "hands_free"
            else:
                self._recording = False
                action = "stop"
        if action == "hands_free":
            self._on_hands_free()
        else:
            self._on_stop()

    def _escape(self) -> None:
        with self._lock:
            if not self._recording:
                return
            self._recording = self._hands_free = False
            self._pressed_at = 0.0
        self._on_cancel()
