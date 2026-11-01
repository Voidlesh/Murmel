"""Lowers the volume of other apps while recording (per-app Windows audio sessions)."""
from __future__ import annotations

import atexit
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_FACTOR = 0.15
CHANGED_BY_USER_TOLERANCE = 0.05


def _sessions():
    import comtypes
    from pycaw.pycaw import AudioUtilities

    comtypes.CoInitialize()
    try:
        own = {os.getpid(), os.getppid()}
        for session in AudioUtilities.GetAllSessions():
            if session.ProcessId and session.ProcessId not in own:
                yield session
    finally:
        comtypes.CoUninitialize()


class Ducker:
    """duck() and restore() run on one worker thread so they never overlap or block recording."""

    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path
        self._ducked: dict[int, tuple[float, float]] = {}  # pid -> (original, ducked)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="duck")
        atexit.register(self._restore)  # the pool is already shut down by then, so call directly

    def duck(self, factor: float = DEFAULT_FACTOR) -> None:
        self._pool.submit(self._duck, factor)

    def restore(self) -> None:
        self._pool.submit(self._restore)

    def restore_now(self) -> None:
        """Synchronous variant for crash recovery."""
        self._pool.submit(self._restore).result(timeout=5)

    def recover_leftover(self) -> None:
        """A crash mid-recording must not leave other apps muted: reload the saved state and restore it."""
        try:
            saved = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._ducked = {int(pid): tuple(vols) for pid, vols in saved.items()}
        except (OSError, ValueError, TypeError):
            return
        self.restore_now()

    def _duck(self, factor: float) -> None:
        try:
            if self._ducked:
                self._restore()
            for session in _sessions():
                volume = session.SimpleAudioVolume
                original = volume.GetMasterVolume()
                ducked = round(original * factor, 4)
                volume.SetMasterVolume(ducked, None)
                self._ducked[session.ProcessId] = (original, ducked)
            self._save()
        except Exception:  # noqa: BLE001 - ducking is a nicety, never break dictation
            log.warning("Audio-Ducking fehlgeschlagen", exc_info=True)

    def _restore(self) -> None:
        if not self._ducked:
            return
        try:
            for session in _sessions():
                entry = self._ducked.get(session.ProcessId)
                if not entry:
                    continue
                original, ducked = entry
                volume = session.SimpleAudioVolume
                if abs(volume.GetMasterVolume() - ducked) <= CHANGED_BY_USER_TOLERANCE:
                    volume.SetMasterVolume(original, None)  # leave it alone if the user changed it meanwhile
        except Exception:  # noqa: BLE001
            log.warning("Audio-Wiederherstellung fehlgeschlagen", exc_info=True)
        finally:
            self._ducked = {}
            self._state_path.unlink(missing_ok=True)

    def _save(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps({str(p): list(v) for p, v in self._ducked.items()}), encoding="utf-8")
        except OSError:
            log.warning("Ducking-Zustand nicht speicherbar", exc_info=True)
