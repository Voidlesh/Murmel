"""Engine orchestrator + WebSocket API on 127.0.0.1 for the Electron UI."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import numpy as np
import websockets
from websockets.asyncio.server import ServerConnection

from . import audio, config, ducking, insights, llm, output, pipeline, style, textproc
from .accounts import AccountStore, AuthError
from .hotkey import HotkeyController, validate_hotkey
from .sessions import Segment, Segmenter
from .store import Store

log = logging.getLogger(__name__)

HOST, PORT = "127.0.0.1", 47821
MIN_DURATION_S = 0.35
KEEP_AUDIO_FILES = 200
SESSION_KEEP_AUDIO = 50  # session recordings kept on disk, counted separately from dictations


@dataclass
class _SessionStream:
    speaker: str  # "you" (microphone) or "them" (system audio)
    recorder: audio.Recorder
    segmenter: Segmenter
    last_preview: float = 0.0  # monotonic time of the last live preview for this stream
SESSION_TICK_S = 1.0  # how often the live audio is taken from the recorder
PREVIEW_INTERVAL_S = 2.0  # live preview refresh, the model is busy for part of this on a slow GPU
PREVIEW_WINDOW_S = 10.0  # a preview only transcribes the newest seconds, so it stays cheap
PREVIEW_MIN_S = 1.0  # shorter speech is too little to show
LEVEL_INTERVAL_S = 0.1  # mean of the scaled block levels per window
ALLOWED_ORIGINS = {None, "null", "file://"}


class Engine:
    def __init__(self) -> None:
        self.accounts = AccountStore(config.DATA_DIR)
        self.account = None
        self.account_dir: Path | None = None
        self.settings = config.load_settings(config.DATA_DIR / "machine.json")
        self.store: Store | None = None
        self.clients: set[ServerConnection] = set()
        self.state = "loading"
        self.state_detail = "Sprachmodell wird geladen …"
        self.hands_free = False
        self.transcriber = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._levels: list[list[float]] = []
        self._band_scalers = self._new_band_scalers()
        self._target: tuple[str, str] = ("", "")
        self._started_at = 0.0
        self.recorder = audio.Recorder(self._on_level)
        self._system_recorder = audio.Recorder(lambda _bands: None)  # Systemaudio, nur für Sitzungen
        self.ducker = ducking.Ducker(config.DATA_DIR / "duck_state.json")
        self.hotkey = HotkeyController(
            on_start=lambda: self._threadsafe(self.start_recording),
            on_stop=lambda: self._threadsafe(self.stop_recording),
            on_cancel=lambda: self._threadsafe(self.cancel_recording),
            on_hands_free=lambda: self._threadsafe(self._enter_hands_free),
        )
        self.session_hotkey = HotkeyController(
            on_start=lambda: self._threadsafe(self._session_toggle),
            on_stop=lambda: self._threadsafe(self._session_toggle),
            on_cancel=lambda: None,  # Esc must not discard a session
            on_hands_free=lambda: None,
        )
        self.session_id: int | None = None
        self._session_running = False
        self._session_task: asyncio.Task | None = None
        self._session_wav: audio.WavWriter | None = None

    # --- lifecycle ---------------------------------------------------------
    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        async with websockets.serve(self._handle_client, HOST, PORT, max_size=2**22):
            log.info("Engine lauscht auf ws://%s:%d", HOST, PORT)
            remembered = self.accounts.remembered()
            if remembered:
                self._activate(remembered)
            self.hotkey.configure(self.settings["hotkey"], self.settings["tap_for_hands_free"])
            self._configure_session_hotkey()
            await asyncio.to_thread(self.ducker.recover_leftover)
            asyncio.create_task(self._level_pump())
            await self._load_model()
            await asyncio.Future()

    # --- accounts ------------------------------------------------------------
    @property
    def settings_path(self) -> Path:
        return (self.account_dir or config.DATA_DIR) / ("settings.json" if self.account_dir else "machine.json")

    def _activate(self, account) -> None:
        if self.store:
            self.store.close()
        self.account = account
        self.account_dir = self.accounts.account_dir(account.id)
        self.settings = config.load_settings(self.account_dir / "settings.json")
        if not self.settings.get("user_name"):
            self.settings = {**self.settings, "user_name": account.name}
        self.store = Store(self.account_dir / "murmel.db")
        self.store.mark_interrupted_sessions()
        log.info("Account aktiv: %s", account.name)

    def _deactivate(self) -> None:
        if self.store:
            self.store.close()
        self.account = self.account_dir = self.store = None

    async def _after_account_change(self, previous: dict[str, Any]) -> None:
        if (previous["hotkey"], previous["tap_for_hands_free"]) != (self.settings["hotkey"], self.settings["tap_for_hands_free"]):
            self.hotkey.configure(self.settings["hotkey"], self.settings["tap_for_hands_free"])
        if previous["session_hotkey"] != self.settings["session_hotkey"]:
            self._configure_session_hotkey()
        await self.broadcast({"type": "account", "account": self.account.public() if self.account else None})
        await self.broadcast(self._state_msg())
        if (previous["model"], previous["device"]) != (self.settings["model"], self.settings["device"]):
            asyncio.create_task(self._load_model())

    def _require_store(self) -> Store:
        if not self.store:
            raise AuthError("Bitte melde dich zuerst an")
        return self.store

    def _require_no_session(self) -> None:
        if self.session_id is not None:
            raise ValueError("Bitte beende zuerst die laufende Sitzung")

    async def _load_model(self) -> None:
        from .stt import Transcriber  # heavy import, keep server responsive first

        await self._set_state("loading", "Sprachmodell wird geladen …")
        try:
            self.transcriber = await asyncio.to_thread(
                Transcriber, self.settings["model"], self.settings["device"]
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("Modell konnte nicht geladen werden")
            await self._set_state("error", f"Modell-Fehler: {exc}")
            return
        await self._set_state("idle", f"{self.transcriber.model_name} · {self.transcriber.device.upper()}")

    def _threadsafe(self, coro_fn: Callable[[], Awaitable[None]]) -> None:
        if self.loop:
            asyncio.run_coroutine_threadsafe(coro_fn(), self.loop)

    # --- recording flow ----------------------------------------------------
    async def start_recording(self) -> None:
        if self.session_id is not None:
            self.hotkey.set_recording(False)
            await self.broadcast({"type": "notice", "text": "Während einer Sitzung ist Diktieren gesperrt."})
            return
        if self.state not in ("idle", "error") or not self.transcriber:
            self.hotkey.set_recording(False)
            return
        if not self.store:
            self.hotkey.set_recording(False)
            await self.broadcast({"type": "notice", "text": "Bitte melde dich in Murmel an, um zu diktieren."})
            return
        try:
            self._target = output.foreground_app()
            if self.settings["copy_fallback"]:
                # warm-up: Electron apps only expose their text fields after the first UI Automation query
                asyncio.get_running_loop().run_in_executor(None, output.focused_text_input)
            self._band_scalers = self._new_band_scalers()
            self.recorder.start(self.settings.get("mic_device"))
            if self.settings.get("duck_audio"):
                self.ducker.duck(float(self.settings.get("duck_level", ducking.DEFAULT_FACTOR)))
        except Exception as exc:  # noqa: BLE001
            log.exception("Aufnahme-Start fehlgeschlagen")
            self.hotkey.set_recording(False)
            await self._set_state("error", f"Mikrofon-Fehler: {exc}")
            return
        self._started_at = time.monotonic()
        self.hands_free = False
        await self._set_state("recording")

    async def _enter_hands_free(self) -> None:
        self.hands_free = True
        await self._set_state(self.state)

    async def cancel_recording(self) -> None:
        if self.recorder.active:
            self.recorder.stop()
        self.ducker.restore()
        self.hotkey.set_recording(False)
        await self._set_state("idle", "Abgebrochen")

    async def stop_recording(self) -> None:
        if not self.recorder.active:
            return
        samples = self.recorder.stop()
        self.ducker.restore()
        self.hotkey.set_recording(False)
        duration = samples.size / audio.SAMPLE_RATE
        if duration < MIN_DURATION_S or audio.is_silent(samples):
            await self._set_state("idle", "Nichts gehört")
            return
        await self._set_state("processing")
        try:
            item = await asyncio.to_thread(self._transcribe_and_paste, samples, duration)
        except Exception as exc:  # noqa: BLE001
            log.exception("Verarbeitung fehlgeschlagen")
            await self._set_state("error", f"Fehler: {exc}")
            return
        if item:
            await self.broadcast({"type": "transcript", "item": item})
            if not item["pasted"]:
                await self.broadcast({"type": "copy_panel", "text": item["text"]})
            await self._set_state("idle", f"{item['words']} Wörter · {item['process_ms']} ms")
        else:
            await self._set_state("idle", "Nichts erkannt")

    def _transcribe_and_paste(self, samples, duration: float, paste: bool = True) -> dict[str, Any] | None:
        started = time.perf_counter()
        s = self.settings
        store = self._require_store()
        vocabulary = store.vocabulary()
        result = self.transcriber.transcribe(samples, s["language"], s["beam_size"], vocabulary)
        if not result.text:
            return None
        app, title = self._target
        category = output.categorize(app, title, s["style_apps"])
        processed = pipeline.process(
            result.text, category, s, store.corrections(), store.snippets(), vocabulary, llm.polish,
            style.build_context(store.style_edits(category)),
        )
        if not processed.text:
            return None
        pasted = paste and not (s["copy_fallback"] and not output.focused_text_input())
        if pasted:
            output.paste_text(processed.text, s["restore_clipboard"])
        audio_path = None
        if s["keep_audio"] and self.account_dir:
            path = self.account_dir / "audio" / f"{int(time.time() * 1000)}.wav"
            audio.save_wav(samples, path)
            audio_path = str(path)
        item = store.add_transcript({
            "raw_text": result.text, "text": processed.text, "words": textproc.count_words(processed.text),
            "duration_s": round(duration, 2), "process_ms": int((time.perf_counter() - started) * 1000),
            "app": app, "window_title": title[:200], "category": category,
            "language": result.language, "audio_path": audio_path,
            "fixes_words": processed.fixes_words, "fixes_dict": processed.fixes_dict,
        })
        item["pasted"] = pasted
        self._prune_audio(store)
        return item

    @staticmethod
    def _prune_audio(store: Store) -> None:
        for transcript_id, path in store.audio_paths_beyond(KEEP_AUDIO_FILES):
            Path(path).unlink(missing_ok=True)
            store.clear_audio_path(transcript_id)

    # --- sessions (long recordings) ------------------------------------------
    @staticmethod
    def _check_hotkeys(settings: dict[str, Any]) -> None:
        dictation = set(validate_hotkey(settings["hotkey"]))
        session_hotkey = (settings.get("session_hotkey") or "").strip()
        if not session_hotkey:
            return
        if set(validate_hotkey(session_hotkey)) == dictation:
            raise ValueError("Die Sitzungs-Taste muss sich von der Diktier-Taste unterscheiden")

    def _configure_session_hotkey(self) -> None:
        hotkey = (self.settings.get("session_hotkey") or "").strip()
        if not hotkey:
            self.session_hotkey.unhook()
            return
        try:
            self.session_hotkey.configure(hotkey, tap_for_hands_free=True)
        except ValueError:
            log.warning("Ungültiger Sitzungs-Hotkey: %s", hotkey)
            self.session_hotkey.unhook()

    async def _session_toggle(self) -> None:
        try:
            if self.session_id is None:
                await self.api_session_start()
            else:
                await self.api_session_stop()
        except Exception as exc:  # noqa: BLE001 - the hotkey has no caller to return the error to
            self.session_hotkey.set_recording(False)
            await self.broadcast({"type": "notice", "text": str(exc)})

    async def api_session_start(self, title: str = "") -> dict[str, Any]:
        store = self._require_store()
        if self.session_id is not None:
            raise ValueError("Es läuft schon eine Sitzung")
        if not self.transcriber or self.state not in ("idle", "error"):
            raise ValueError("Bitte warte, bis Murmel bereit ist")
        started = time.time()
        name = title.strip() or time.strftime("Sitzung %d.%m.%Y %H:%M", time.localtime(started))
        session = store.create_session(name, started, self.settings["language"])
        wav = None
        try:
            wav = self._open_session_audio(session["id"])
            self.recorder.start(self.settings.get("mic_device"))
        except Exception as exc:
            if wav:
                wav.close()
            store.finish_session(session["id"], time.time(), "error")
            raise ValueError(f"Aufnahme konnte nicht starten: {exc}") from exc
        streams = self._start_session_streams()
        self.session_id = session["id"]
        self._session_running = True
        self._session_wav = wav
        self.session_hotkey.set_recording(True)
        self._session_task = asyncio.create_task(self._session_loop(session["id"], streams))
        await self.broadcast({"type": "session_status", "session": session})
        if len(streams) == 1 and self.settings.get("session_system_audio"):
            await self.broadcast({"type": "notice", "text": "Systemaudio ist nicht verfügbar, nur dein Mikrofon wird aufgenommen"})
        return session

    def _start_session_streams(self) -> list["_SessionStream"]:
        """Microphone is 'you'. System audio (the other side of a call) is 'them' and is optional."""
        streams = [_SessionStream("you", self.recorder, Segmenter())]
        if self.settings.get("session_system_audio"):
            try:
                self._system_recorder.start(loopback=True)
            except Exception:  # noqa: BLE001 - the session keeps going with the microphone alone
                log.exception("Systemaudio-Aufnahme konnte nicht starten")
            else:
                streams.append(_SessionStream("them", self._system_recorder, Segmenter()))
        return streams

    async def api_session_stop(self) -> dict[str, Any]:
        if self.session_id is None or self._session_task is None:
            raise ValueError("Keine Sitzung aktiv")
        session_id = self.session_id
        self._session_running = False
        self.session_hotkey.set_recording(False)
        await self._session_task
        return self._require_store().get_session(session_id)

    def _open_session_audio(self, session_id: int) -> audio.WavWriter | None:
        if not (self.settings.get("session_keep_audio") and self.account_dir):
            return None
        path = self.account_dir / "audio" / f"session-{session_id}.wav"
        self._require_store().set_session_audio(session_id, str(path))
        return audio.WavWriter(path)

    async def _session_loop(self, session_id: int, streams: list["_SessionStream"]) -> None:
        store = self._require_store()
        try:
            while self._session_running:
                await asyncio.sleep(SESSION_TICK_S)
                for stream in streams:
                    await self._session_feed(session_id, stream, stream.recorder.drain())
                    await self._session_preview(session_id, stream)
            for stream in streams:
                await self._session_feed(session_id, stream, stream.recorder.stop())
                last = stream.segmenter.flush()
                if last:
                    await self._session_save(session_id, stream.speaker, last)
            store.finish_session(session_id, time.time(), "done")
            if self.settings["llm"].get("enabled"):
                await self._run_summary(session_id)
        except Exception:  # noqa: BLE001 - keep the engine alive, the session is marked as failed
            log.exception("Sitzung fehlgeschlagen")
            store.finish_session(session_id, time.time(), "error")
        finally:
            for stream in streams:
                if stream.recorder.active:
                    stream.recorder.stop()
            if self._session_wav:
                self._session_wav.close()
                self._session_wav = None
            self.session_id = None
        self._prune_session_audio(store)
        await self.broadcast({"type": "session_status", "session": store.get_session(session_id)})

    async def _session_feed(self, session_id: int, stream: "_SessionStream", samples: np.ndarray) -> None:
        if stream.speaker == "you" and self._session_wav and samples.size:  # the saved audio is the microphone
            self._session_wav.write(samples)
        for segment in stream.segmenter.feed(samples):
            await self._session_save(session_id, stream.speaker, segment)

    async def _session_preview(self, session_id: int, stream: "_SessionStream") -> None:
        """Provisional text for the speech that is not cut yet. The final segment replaces it when the pause comes."""
        if not self.settings.get("session_live_preview"):
            return
        now = time.monotonic()
        if now - stream.last_preview < PREVIEW_INTERVAL_S:
            return
        stream.last_preview = now
        start_s, tail = stream.segmenter.pending(int(PREVIEW_WINDOW_S * audio.SAMPLE_RATE))
        text = ""
        if tail.size >= int(PREVIEW_MIN_S * audio.SAMPLE_RATE) and not audio.is_silent(tail):
            text = await asyncio.to_thread(self._transcribe_session_segment, tail)
        await self.broadcast({
            "type": "session_preview", "session_id": session_id, "speaker": stream.speaker,
            "start_s": start_s, "text": text,
        })

    async def _session_save(self, session_id: int, speaker: str, segment: Segment) -> None:
        if segment.end_s - segment.start_s < MIN_DURATION_S:  # too short to transcribe reliably
            return
        text = await asyncio.to_thread(self._transcribe_session_segment, segment.samples)
        if not text:
            return
        row = self._require_store().add_session_segment(
            session_id, segment.start_s, segment.end_s, text, speaker=speaker
        )
        await self.broadcast({"type": "session_segment", "session_id": session_id, "segment": row})

    def _transcribe_session_segment(self, samples: np.ndarray) -> str:
        s = self.settings
        store = self._require_store()
        result = self.transcriber.transcribe(samples, s["language"], s["beam_size"], store.vocabulary())
        text = textproc.remove_fillers(result.text) if s["remove_fillers"] else result.text
        return textproc.apply_corrections(text, store.corrections()).strip()

    async def _run_summary(self, session_id: int) -> None:
        store = self._require_store()
        store.set_session_status(session_id, "processing")
        text = " ".join(seg["text"] for seg in store.session_segments(session_id))
        try:
            summary, items = await asyncio.to_thread(llm.summarize_session, text, self.settings["llm"])
        except Exception:  # noqa: BLE001 - the transcript stays usable without a summary
            log.exception("Zusammenfassung fehlgeschlagen")
            store.set_session_status(session_id, "error")
            return
        store.set_session_summary(session_id, summary, items)
        store.set_session_status(session_id, "done")

    @staticmethod
    def _prune_session_audio(store: Store) -> None:
        for session_id, path in store.session_audio_paths_beyond(SESSION_KEEP_AUDIO):
            Path(path).unlink(missing_ok=True)
            store.clear_session_audio_path(session_id)

    async def api_session_list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._require_store().list_sessions(limit, offset)

    async def api_session_get(self, id: int) -> dict[str, Any]:  # noqa: A002
        store = self._require_store()
        return {**store.get_session(id), "segments": store.session_segments(id)}

    async def api_session_update_notes(self, id: int, notes: str) -> dict[str, Any]:  # noqa: A002
        store = self._require_store()
        store.update_session_notes(id, notes)
        return store.get_session(id)

    async def api_session_delete(self, id: int) -> None:  # noqa: A002
        if id == self.session_id:
            raise ValueError("Die laufende Sitzung kann nicht gelöscht werden")
        path = self._require_store().delete_session(id)
        if path:
            Path(path).unlink(missing_ok=True)

    async def api_session_summarize(self, id: int) -> dict[str, Any]:  # noqa: A002
        store = self._require_store()
        if id == self.session_id:
            raise ValueError("Die laufende Sitzung kann noch nicht zusammengefasst werden")
        if not self.settings["llm"].get("enabled"):
            raise ValueError("Die KI-Zusammenfassung ist deaktiviert")
        await self._run_summary(id)
        session = store.get_session(id)
        await self.broadcast({"type": "session_status", "session": session})
        return session

    # --- broadcasting ------------------------------------------------------
    @staticmethod
    def _new_band_scalers() -> list[audio.LevelScaler]:
        return [audio.LevelScaler(audio.BAND_FLOOR_MIN_DB, audio.BAND_RANGE_DB) for _ in range(audio.BAND_COUNT)]

    def _on_level(self, bands_db) -> None:
        self._levels.append([scaler.scale(float(db)) for scaler, db in zip(self._band_scalers, bands_db)])

    async def _level_pump(self) -> None:
        while True:
            await asyncio.sleep(LEVEL_INTERVAL_S)
            levels, self._levels = self._levels, []
            if levels and self.recorder.active:
                bands = [round(sum(col) / len(col), 3) for col in zip(*levels)]
                await self.broadcast({"type": "level", "value": round(sum(bands) / len(bands), 3), "bands": bands})

    async def _set_state(self, state: str, detail: str = "") -> None:
        self.state, self.state_detail = state, detail
        if state != "recording":
            self.hands_free = False
        await self.broadcast(self._state_msg())

    def _state_msg(self) -> dict[str, Any]:
        return {
            "type": "state", "state": self.state, "detail": self.state_detail,
            "hands_free": self.hands_free, "hotkey": self.settings["hotkey"],
            "sounds": self.settings["sounds"],
            "account": self.account.public() if self.account else None,
        }

    async def broadcast(self, msg: dict[str, Any]) -> None:
        if not self.clients:
            return
        data = json.dumps(msg, ensure_ascii=False)
        await asyncio.gather(*(c.send(data) for c in list(self.clients)), return_exceptions=True)

    # --- client API --------------------------------------------------------
    async def _handle_client(self, ws: ServerConnection) -> None:
        origin = ws.request.headers.get("Origin") if ws.request else None
        if origin not in ALLOWED_ORIGINS and not str(origin).startswith("file://"):
            log.warning("Verbindung von fremder Origin abgelehnt: %s", origin)
            await ws.close(1008, "origin not allowed")
            return
        self.clients.add(ws)
        try:
            await ws.send(json.dumps(self._state_msg(), ensure_ascii=False))
            async for raw in ws:
                await self._dispatch(ws, raw)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.discard(ws)

    async def _dispatch(self, ws: ServerConnection, raw: str | bytes) -> None:
        try:
            req = json.loads(raw)
            method = getattr(self, "api_" + str(req.get("method", "")), None)
            if method is None:
                raise ValueError(f"Unbekannte Methode: {req.get('method')}")
            result = await method(**(req.get("params") or {}))
            reply = {"id": req.get("id"), "result": result}
        except Exception as exc:  # noqa: BLE001 - every error goes back to the UI
            log.warning("API-Fehler: %s", exc)
            reply = {"id": req.get("id") if isinstance(req, dict) else None, "error": str(exc)}
        await ws.send(json.dumps(reply, ensure_ascii=False, default=str))

    async def api_get_settings(self) -> dict[str, Any]:
        return self.settings

    async def api_set_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        new = config.update_settings(self.settings, patch)
        self._check_hotkeys(new)  # validate before anything changes, so a bad value is never saved
        if "hotkey" in patch or "tap_for_hands_free" in patch:
            self.hotkey.configure(new["hotkey"], new["tap_for_hands_free"])
        if "session_hotkey" in patch:
            self._configure_session_hotkey()
        reload_model = any(k in patch for k in ("model", "device"))
        self.settings = new
        config.save_settings(new, self.settings_path)
        await self.broadcast(self._state_msg())
        if reload_model:
            asyncio.create_task(self._load_model())
        return new

    async def api_toggle(self) -> None:
        self.hotkey.toggle_from_ui()

    async def api_cancel(self) -> None:
        await self.cancel_recording()

    async def api_history(self, limit: int = 50, offset: int = 0, query: str = "") -> list[dict[str, Any]]:
        return self._require_store().list_transcripts(limit, offset, query)

    async def api_edit_transcript(self, id: int, text: str, learn: bool = True) -> dict[str, Any]:  # noqa: A002
        before = self._require_store().get_transcript(id)
        item = self._require_store().update_transcript_text(id, text.strip(), textproc.count_words(text))
        learned = textproc.learn_corrections(before["text"], text) if learn else []
        for c in learned:
            self._require_store().upsert_dictionary(c.wrong, c.right, auto=True)
        return {"item": item, "learned": [{"wrong": c.wrong, "right": c.right} for c in learned]}

    async def api_delete_transcript(self, id: int) -> None:  # noqa: A002
        path = self._require_store().delete_transcript(id)
        if path:
            Path(path).unlink(missing_ok=True)

    async def api_paste_again(self, id: int) -> None:  # noqa: A002
        item = self._require_store().get_transcript(id)
        await asyncio.to_thread(output.set_clipboard_text, item["text"])

    async def api_audio(self, id: int) -> str | None:  # noqa: A002
        path = self._require_store().get_transcript(id).get("audio_path")
        return Path(path).as_uri() if path and Path(path).exists() else None

    async def api_stats(self, days: int | None = 30) -> dict[str, Any]:
        return self._require_store().stats(days, self.settings["typing_wpm"])

    async def api_dictionary(self) -> list[dict[str, Any]]:
        return self._require_store().list_dictionary()

    async def api_dictionary_save(self, word: str, replacement: str | None = None) -> dict[str, Any]:
        return self._require_store().upsert_dictionary(word, replacement)

    async def api_dictionary_suggestions(self) -> list[str]:
        return self._require_store().dictionary_suggestions()

    async def api_dictionary_delete(self, id: int) -> None:  # noqa: A002
        self._require_store().delete_dictionary(id)

    async def api_snippets(self) -> list[dict[str, Any]]:
        return self._require_store().list_snippets()

    async def api_snippet_save(self, trigger: str, expansion: str, id: int | None = None) -> dict[str, Any]:  # noqa: A002
        return self._require_store().upsert_snippet(trigger, expansion, id)

    async def api_snippet_delete(self, id: int) -> None:  # noqa: A002
        self._require_store().delete_snippet(id)

    async def api_microphones(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(audio.list_microphones)

    async def api_llm_check(self, base_url: str | None = None) -> dict[str, Any]:
        cfg = {**self.settings["llm"], **({"base_url": base_url} if base_url else {})}
        return await asyncio.to_thread(llm.check, cfg)

    async def api_preview(self, text: str, category: str = "other") -> str:
        """Run the text pipeline on typed text (used by the Style page)."""
        store = self._require_store()
        result = await asyncio.to_thread(
            pipeline.process, text, category, self.settings, store.corrections(),
            store.snippets(), store.vocabulary(), llm.polish, style.build_context(store.style_edits(category)),
        )
        return result.text

    async def api_status(self) -> dict[str, Any]:
        return self._state_msg()

    # --- insights ------------------------------------------------------------
    async def api_usage(self, days: int | None = None) -> dict[str, Any]:
        since = time.time() - days * 86400 if days else 0
        return insights.usage(self._require_store().analysis_rows(since))

    async def api_voice_profile(self) -> dict[str, Any]:
        return await asyncio.to_thread(insights.voice_profile, self._require_store().analysis_rows())

    async def api_activity(self, days: int = 182) -> list[dict[str, Any]]:
        return self._require_store().daily_activity(max(7, min(int(days), 366)))

    # --- auth ----------------------------------------------------------------
    async def api_auth_status(self) -> dict[str, Any]:
        return {"account": self.account.public() if self.account else None,
                "accounts": self.accounts.list_public()}

    async def api_auth_register(self, name: str, email: str, password: str) -> dict[str, Any]:
        account = await asyncio.to_thread(self.accounts.register, name, email, password)
        return await self._login_as(account, remember=True)

    async def api_auth_login(self, login: str, password: str, remember: bool = True) -> dict[str, Any]:
        account = await asyncio.to_thread(self.accounts.login, login, password)
        return await self._login_as(account, remember)

    async def _login_as(self, account, remember: bool) -> dict[str, Any]:
        self._require_no_session()
        if self.recorder.active:
            await self.cancel_recording()
        previous = self.settings
        self._activate(account)
        self.accounts.set_active(account.id if remember else None)
        await self._after_account_change(previous)
        return {"account": account.public(), "settings": self.settings}

    async def api_auth_logout(self) -> None:
        self._require_no_session()
        if self.recorder.active:
            await self.cancel_recording()
        previous = self.settings
        self._deactivate()
        self.accounts.set_active(None)
        self.settings = config.load_settings(config.DATA_DIR / "machine.json")
        await self._after_account_change(previous)

    async def api_account_update(self, name: str, email: str) -> dict[str, Any]:
        self._require_store()
        self.account = self.accounts.update_profile(self.account.id, name, email)
        await self.broadcast({"type": "account", "account": self.account.public()})
        return self.account.public()

    async def api_account_password(self, old: str, new: str) -> None:
        self._require_store()
        await asyncio.to_thread(self.accounts.change_password, self.account.id, old, new)

    async def api_account_delete(self, password: str) -> None:
        self._require_store()
        account_id = self.account.id
        await asyncio.to_thread(self.accounts.login, self.account.email, password)  # verify before closing the DB
        await self.api_auth_logout()
        await asyncio.to_thread(self.accounts.delete, account_id, password)

    async def api_transcribe_wav(self, path: str) -> dict[str, Any] | None:
        """Run a 16 kHz mono wav through the full pipeline without pasting (diagnostics/tests)."""
        self._require_no_session()
        import wave

        import numpy as np

        if not self.transcriber:
            raise RuntimeError("Modell noch nicht geladen")
        with wave.open(path) as w:
            if w.getframerate() != audio.SAMPLE_RATE or w.getnchannels() != 1:
                raise ValueError("WAV muss 16 kHz mono sein")
            samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        self._target = ("test.exe", "Murmel Selbsttest")
        item = await asyncio.to_thread(self._transcribe_and_paste, samples, samples.size / audio.SAMPLE_RATE, False)
        if item:
            await self.broadcast({"type": "transcript", "item": item})
        return item
