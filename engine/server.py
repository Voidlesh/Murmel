"""Engine orchestrator + WebSocket API on 127.0.0.1 for the Electron UI."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import numpy as np
import websockets
from websockets.asyncio.server import ServerConnection

from . import audio, config, ducking, export, insights, llm, output, pipeline, style, textproc
from .accounts import AccountStore, AuthError
from .hotkey import HotkeyController, validate_hotkey
from .sessions import Segment, Segmenter
from .store import Store

log = logging.getLogger(__name__)

HOST, PORT = "127.0.0.1", 47821
MIN_DURATION_S = 0.35
KEEP_AUDIO_FILES = 200
SESSION_KEEP_AUDIO = 50  # session recordings kept on disk, counted separately from dictations


SESSION_SOURCES = ("both", "desktop", "mic")
DEVICE_CHECK_S = 8.0  # how often the default playback device is compared with the recorded one
DESKTOP_SILENT_WARN_S = 20.0  # desktop audio this long without sound gets a visible warning
SILENT_DB = -55.0  # quieter than this counts as no sound for the warning
SESSION_LEVEL_INTERVAL_S = 0.15
MAX_TICK_FAILURES = 30  # this many failed ticks in a row (about half a minute) end the session


@dataclass
class _SessionStream:
    speaker: str  # "you" (microphone) or "them" (system audio)
    recorder: audio.Recorder
    segmenter: Segmenter
    last_preview: float = 0.0  # monotonic time of the last live preview for this stream
    preview_task: asyncio.Task | None = None
    reconnect_failed: bool = False


@dataclass
class _JobContext:
    language: str
    terms: list[str]


class _LiveSession:
    """Everything that belongs to the running session: streams, audio files, the transcription queue."""

    def __init__(self, session_id: int, source: str, language: str, terms: list[str]) -> None:
        self.id = session_id
        self.source = source
        self.language = language
        self.terms = terms
        self.started = time.time()
        self.streams: list[_SessionStream] = []
        self.mix: audio.WavWriter | None = None
        self.tracks: dict[str, audio.WavWriter] = {}
        self._mix_pending: dict[str, np.ndarray] = {}
        self.queue: asyncio.Queue = asyncio.Queue()
        self.queued_s = 0.0  # audio waiting for transcription, shown as lag
        self.device_checked = time.monotonic()
        self.desktop_loud_at = time.monotonic()
        self.silence_warned = False
        self.transcribe_failed = False
        self.device_task: asyncio.Task | None = None
        self.device_seen = ""  # answer of the last background device query, read by the next tick

    def enqueue(self, speaker: str, segment: Segment) -> None:
        self.queued_s += segment.end_s - segment.start_s
        self.queue.put_nowait((speaker, segment))

    def write_mix(self, drained: dict[str, np.ndarray], final: bool) -> None:
        """Sum the sources sample by sample; what one source has ahead waits for the other."""
        if not self.mix:
            return
        for speaker, samples in drained.items():
            self._mix_pending[speaker] = np.concatenate([self._mix_pending.get(speaker, np.zeros(0, np.float32)), samples])
        pending = list(self._mix_pending.values())
        if not pending:
            return
        size = max(p.size for p in pending) if final else min(p.size for p in pending)
        if not size:
            return
        mixed = np.zeros(size, dtype=np.float32)
        for speaker, samples in self._mix_pending.items():
            part = samples[:size]
            mixed[: part.size] += part
            self._mix_pending[speaker] = samples[size:]
        self.mix.write(np.clip(mixed, -1.0, 1.0))

    def close_audio(self) -> None:
        for writer in [self.mix, *self.tracks.values()]:
            if writer:
                with contextlib.suppress(Exception):
                    writer.close()


def _track_path(main: Path, speaker: str) -> Path:
    return main.with_name(f"{main.stem}-{'desktop' if speaker == 'them' else 'mic'}.wav")


def _audio_family(main: Path) -> list[Path]:
    return [main, _track_path(main, "them"), _track_path(main, "you")]


def _session_files(session: dict[str, Any]) -> dict[str, Path]:
    if not session.get("audio_path"):
        return {}
    main = Path(session["audio_path"])
    return {"mix": main, "desktop": _track_path(main, "them"), "mic": _track_path(main, "you")}


def _retranscribe_tracks(session: dict[str, Any]) -> list[tuple[str, Path]]:
    """Which file belongs to which speaker. Older sessions only kept the microphone, in the main file."""
    files = _session_files(session)
    if not files:
        return []
    tracks = [(speaker, files[key]) for speaker, key in (("them", "desktop"), ("you", "mic")) if files[key].exists()]
    if tracks:
        return tracks
    if not files["mix"].exists():
        return []
    speaker = {"": "you", "mic": "you"}.get(session.get("source") or "", "them")
    return [(speaker, files["mix"])]


def _wav_seconds(path: Path) -> float:
    import wave

    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / float(wav.getframerate() or 1)


def _convert_to_wav(source: Path, target: Path) -> float:
    """Any audio or video file to 16 kHz mono WAV (PyAV via faster-whisper). Returns the duration in seconds."""
    from faster_whisper.audio import decode_audio

    samples = decode_audio(str(source), sampling_rate=audio.SAMPLE_RATE)
    writer = audio.WavWriter(target)
    try:
        for i in range(0, samples.size, audio.SAMPLE_RATE * 30):
            writer.write(samples[i:i + audio.SAMPLE_RATE * 30])
    finally:
        writer.close()
    return samples.size / audio.SAMPLE_RATE
SESSION_TICK_S = 1.0  # how often the live audio is taken from the recorder
PREVIEW_INTERVAL_S = 0.5  # pause between live previews, one pass on the GPU takes about 0.7 s with the large model
PREVIEW_WINDOW_S = 10.0  # a preview only transcribes the newest seconds, so it stays cheap
PREVIEW_MIN_S = 1.0  # shorter speech is too little to show
DICTATION_PREVIEW_MAX_S = 30.0  # a held key rarely lasts longer, the preview shows the newest part of it
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
        self._dictation_preview: asyncio.Task | None = None
        self._session_running = False
        self._session_task: asyncio.Task | None = None
        self._session_levels_task: asyncio.Task | None = None
        self._live: _LiveSession | None = None
        self._jobs: dict[int, asyncio.Task] = {}  # background re-runs and imports by session id

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
        self._repair_session_audio()
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
        if self._stt_info()["fallback"]:
            await self.broadcast({
                "type": "notice", "warning": True,
                "text": "Achtung: Die Grafikkarte ist nicht nutzbar. Murmel nutzt das kleine CPU-Modell, "
                        "Transkripte werden ungenauer. NVIDIA-Treiber prüfen.",
            })

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
        if self.settings.get("session_live_preview"):
            self._dictation_preview = asyncio.create_task(self._dictation_preview_loop())

    async def _dictation_preview_loop(self) -> None:
        """Shows the text while the key is still held. The pasted text is still transcribed from the full audio at the end."""
        while True:
            await asyncio.sleep(PREVIEW_INTERVAL_S)
            samples = self.recorder.peek(int(DICTATION_PREVIEW_MAX_S * audio.SAMPLE_RATE))
            text = ""
            if samples.size >= int(PREVIEW_MIN_S * audio.SAMPLE_RATE) and not audio.is_silent(samples):
                text = await asyncio.to_thread(self._transcribe_preview, samples)
            await self.broadcast({"type": "dictation_preview", "text": text})

    def _transcribe_preview(self, samples: np.ndarray) -> str:
        return self.transcriber.transcribe(samples, self.settings["language"], 1, []).text.strip()

    async def _stop_dictation_preview(self) -> None:
        task, self._dictation_preview = self._dictation_preview, None
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.broadcast({"type": "dictation_preview", "text": ""})

    async def _enter_hands_free(self) -> None:
        self.hands_free = True
        await self._set_state(self.state)

    async def cancel_recording(self) -> None:
        await self._stop_dictation_preview()
        if self.recorder.active:
            self.recorder.stop()
        self.ducker.restore()
        self.hotkey.set_recording(False)
        await self._set_state("idle", "Abgebrochen")

    async def stop_recording(self) -> None:
        if not self.recorder.active:
            return
        await self._stop_dictation_preview()
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

    # --- session lifecycle ---------------------------------------------------
    def _session_source(self, source: str | None) -> str:
        source = source or self.settings.get("session_source") or "both"
        if source not in SESSION_SOURCES:
            raise ValueError(f"Unbekannte Quelle: {source}")
        if source == "both" and not self.settings.get("session_system_audio", True):
            return "mic"  # older setting: system audio switched off
        return source

    async def api_session_start(
        self, title: str = "", language: str | None = None, terms: str = "", source: str | None = None,
    ) -> dict[str, Any]:
        store = self._require_store()
        if self.session_id is not None:
            raise ValueError("Es läuft schon eine Sitzung")
        if not self.transcriber or self.state not in ("idle", "error"):
            raise ValueError("Bitte warte, bis Murmel bereit ist")
        source = self._session_source(source)
        language = (language or self.settings["language"]).strip()
        terms = ", ".join(t for t in (x.strip() for x in re.split(r"[,;\n]", terms or "")) if t)
        started = time.time()
        name = title.strip() or time.strftime("Sitzung %d.%m.%Y %H:%M", time.localtime(started))
        session = store.create_session(name, started, language, source=source, terms=terms)
        live = _LiveSession(session["id"], source, language, [t.strip() for t in terms.split(",") if t.strip()])
        notices: list[str] = []
        try:
            if source in ("both", "desktop"):
                try:
                    self._system_recorder.start(loopback=True)
                except Exception as exc:
                    raise ValueError(
                        f"Desktop-Audio konnte nicht starten: {exc}. Prüfe, ob ein Wiedergabegerät aktiv ist."
                    ) from exc
                live.streams.append(_SessionStream("them", self._system_recorder, Segmenter()))
            if source in ("both", "mic"):
                try:
                    self.recorder.start(self.settings.get("mic_device"), fill_gaps=True)
                except Exception as exc:
                    if source == "mic":
                        raise ValueError(f"Aufnahme konnte nicht starten: {exc}") from exc
                    log.exception("Mikrofon konnte nicht starten, Sitzung läuft nur mit Desktop-Audio")
                    notices.append(f"Mikrofon nicht verfügbar ({exc}), aufgenommen wird nur das Desktop-Audio.")
                else:
                    live.streams.insert(0, _SessionStream("you", self.recorder, Segmenter()))
            self._open_session_audio(live)
        except Exception as exc:
            for stream in live.streams:
                with contextlib.suppress(Exception):
                    stream.recorder.stop()
            live.close_audio()
            store.finish_session(session["id"], time.time(), "error")
            raise exc if isinstance(exc, ValueError) else ValueError(f"Aufnahme konnte nicht starten: {exc}") from exc
        self.session_id = session["id"]
        self._live = live
        self._session_running = True
        self.session_hotkey.set_recording(True)
        self._session_task = asyncio.create_task(self._session_loop(live))
        self._session_levels_task = asyncio.create_task(self._session_level_loop(live))
        await self._broadcast_session(session["id"])
        for text in notices:
            await self.broadcast({"type": "notice", "text": text})
        return self._session_payload(session["id"])

    async def api_session_stop(self) -> dict[str, Any]:
        if self.session_id is None or self._session_task is None:
            raise ValueError("Es läuft keine Sitzung")
        session_id = self.session_id
        self._session_running = False
        self.session_hotkey.set_recording(False)
        await self._session_task
        return self._session_payload(session_id)

    def _open_session_audio(self, live: "_LiveSession") -> None:
        """Mixed track (the session's main file) plus one file per source, all crash-safe."""
        if not (self.settings.get("session_keep_audio") and self.account_dir):
            return
        main = self.account_dir / "audio" / f"session-{live.id}.wav"
        live.mix = audio.WavWriter(main)
        if len(live.streams) > 1:
            for stream in live.streams:
                live.tracks[stream.speaker] = audio.WavWriter(_track_path(main, stream.speaker))
        self._require_store().set_session_audio(live.id, str(main))

    async def _session_loop(self, live: "_LiveSession") -> None:
        """Capture only: drain, write audio, cut segments. Transcription runs in its own worker, so a slow
        transcription never delays the audio files or the watchdog."""
        store = self._require_store()
        worker = asyncio.create_task(self._session_worker(live))
        status = "done"
        failures = 0
        try:
            while self._session_running:
                await asyncio.sleep(SESSION_TICK_S)
                try:
                    self._session_capture(live, final=False)
                    await self._session_watchdog(live)
                    for stream in live.streams:
                        self._session_preview_soon(live, stream)
                    if failures:
                        failures = 0
                        await self._session_clear(live, "loop_error")
                except Exception as exc:  # noqa: BLE001 - one bad tick must not end a lecture
                    failures += 1
                    log.exception("Fehler in der Sitzungsschleife (%d in Folge)", failures)
                    if failures == 1:
                        await self._session_warn(live, "loop_error", f"Kurzer Aufnahmefehler: {exc}. Die Aufnahme läuft weiter.")
                    if failures >= MAX_TICK_FAILURES:
                        raise
            self._session_capture(live, final=True)
        except Exception:  # noqa: BLE001 - keep the engine alive, keep what was recorded
            log.exception("Sitzung fehlgeschlagen")
            status = "interrupted"
        finally:
            for stream in live.streams:
                if stream.recorder.active:
                    with contextlib.suppress(Exception):
                        stream.recorder.stop()
            live.close_audio()
        store.set_session_ended(live.id, time.time())
        await self.broadcast({"type": "session_finishing", "session_id": live.id, "remaining_s": round(live.queued_s, 1)})
        live.queue.put_nowait(None)
        try:
            await worker
        except Exception:  # noqa: BLE001
            log.exception("Transkription der Sitzung fehlgeschlagen")
            status = "interrupted"
        if self._session_levels_task:
            self._session_levels_task.cancel()
        if live.device_task and not live.device_task.done():
            live.device_task.cancel()
        store.set_session_status(live.id, status)
        self.session_id = None
        self._live = None
        self._prune_session_audio(store)
        await self._broadcast_session(live.id)

    def _session_capture(self, live: "_LiveSession", final: bool) -> None:
        drained = {}
        for stream in live.streams:
            samples = stream.recorder.stop() if final else stream.recorder.drain()
            drained[stream.speaker] = samples
            writer = live.tracks.get(stream.speaker)
            if writer:
                writer.write(samples)
            segments = stream.segmenter.feed(samples)
            if final and (last := stream.segmenter.flush()):
                segments.append(last)
            for segment in segments:
                live.enqueue(stream.speaker, segment)
        live.write_mix(drained, final)

    async def _session_worker(self, live: "_LiveSession") -> None:
        """Transcribes the queued segments one by one. A failing segment is skipped, the next ones still run;
        the audio is kept, so 'Transkript neu erzeugen' can fill the gap later."""
        while (item := await live.queue.get()) is not None:
            speaker, segment = item
            try:
                await self._session_save(live, speaker, segment)
                if live.transcribe_failed:
                    live.transcribe_failed = False
                    await self._session_clear(live, "transcribe_error")
            except Exception as exc:  # noqa: BLE001 - keep transcribing the rest of the lecture
                log.exception("Abschnitt %.0f-%.0f s nicht transkribiert", segment.start_s, segment.end_s)
                if not live.transcribe_failed:
                    live.transcribe_failed = True
                    await self._session_warn(
                        live, "transcribe_error",
                        f"Ein Abschnitt konnte nicht transkribiert werden ({exc}). Das Audio ist gespeichert, "
                        "nach der Aufnahme hilft „Transkript neu erzeugen“.",
                    )
            finally:
                live.queued_s = max(0.0, live.queued_s - (segment.end_s - segment.start_s))

    async def _session_warn(self, live: "_LiveSession", kind: str, text: str) -> None:
        await self.broadcast({"type": "session_warning", "session_id": live.id, "kind": kind, "text": text})

    async def _session_clear(self, live: "_LiveSession", kind: str) -> None:
        await self.broadcast({"type": "session_warning", "session_id": live.id, "kind": "clear", "clears": kind})

    def _session_preview_soon(self, live: "_LiveSession", stream: "_SessionStream") -> None:
        """Provisional text for the speech that is not cut yet; runs in the background and never overlaps itself."""
        if not self.settings.get("session_live_preview") or stream.preview_task and not stream.preview_task.done():
            return
        stream.preview_task = asyncio.create_task(self._session_preview(live, stream))

    async def _session_preview(self, live: "_LiveSession", stream: "_SessionStream") -> None:
        now = time.monotonic()
        if now - stream.last_preview < PREVIEW_INTERVAL_S:
            return
        stream.last_preview = now
        start_s, tail = stream.segmenter.pending(int(PREVIEW_WINDOW_S * audio.SAMPLE_RATE))
        text = ""
        if tail.size >= int(PREVIEW_MIN_S * audio.SAMPLE_RATE) and not audio.is_silent(tail):
            text = await asyncio.to_thread(self._transcribe_session_segment, live, tail)
        await self.broadcast({
            "type": "session_preview", "session_id": live.id, "speaker": stream.speaker,
            "start_s": start_s, "text": text,
        })

    async def _session_save(self, live: "_LiveSession", speaker: str, segment: Segment) -> None:
        if segment.end_s - segment.start_s < MIN_DURATION_S:  # too short to transcribe reliably
            return
        text = await asyncio.to_thread(self._transcribe_session_segment, live, segment.samples)
        if not text:
            return
        row = self._require_store().add_session_segment(live.id, segment.start_s, segment.end_s, text, speaker=speaker)
        await self.broadcast({"type": "session_segment", "session_id": live.id, "segment": row})

    def _transcribe_session_segment(self, live: "_LiveSession | _JobContext", samples: np.ndarray) -> str:
        s = self.settings
        store = self._require_store()
        vocabulary = [*live.terms, *store.vocabulary()]
        result = self.transcriber.transcribe(samples, live.language, s["beam_size"], vocabulary, strict=True)
        text = textproc.strip_hallucinations(result.text)
        text = textproc.remove_fillers(text) if s["remove_fillers"] else text
        return textproc.apply_corrections(text, store.corrections()).strip()

    # --- session watchdog and meters ------------------------------------------
    async def _session_watchdog(self, live: "_LiveSession") -> None:
        now = time.monotonic()
        for stream in live.streams:
            healthy = getattr(stream.recorder, "healthy", lambda: True)()
            if not healthy:
                await self._session_reconnect(live, stream, "Stream unterbrochen")
                continue
            if stream.speaker == "them":
                await self._session_device_check(live, stream, now)
        await self._session_silence_check(live, now)

    async def _session_device_check(self, live: "_LiveSession", stream: "_SessionStream", now: float) -> None:
        """Compare the recorded playback device with the current Windows default. The question runs in a
        child process that takes a moment, so it runs in the background and the tick only reads the answer."""
        current, live.device_seen = live.device_seen, ""
        recorded = getattr(stream.recorder, "device_name", "")
        if current and recorded and current != recorded:
            await self._session_reconnect(live, stream, f"Wiedergabegerät gewechselt zu {current}")
        busy = live.device_task is not None and not live.device_task.done()
        if not busy and now - live.device_checked >= DEVICE_CHECK_S:
            live.device_checked = now
            live.device_task = asyncio.create_task(self._session_query_device(live))

    @staticmethod
    async def _session_query_device(live: "_LiveSession") -> None:
        try:
            live.device_seen = await asyncio.to_thread(audio.default_loopback_name)
        except Exception:  # noqa: BLE001 - no playback device at the moment
            live.device_seen = ""

    async def _session_reconnect(self, live: "_LiveSession", stream: "_SessionStream", reason: str) -> None:
        label = "Desktop-Audio" if stream.speaker == "them" else "Mikrofon"
        try:
            await asyncio.to_thread(stream.recorder.restart)
        except Exception as exc:  # noqa: BLE001 - try again on the next tick
            log.warning("%s: Neuverbindung fehlgeschlagen: %s", label, exc)
            if not stream.reconnect_failed:
                stream.reconnect_failed = True
                await self._session_warn(
                    live, f"stream_lost_{stream.speaker}",
                    f"{label} ist ausgefallen ({reason}). Murmel versucht weiter, es neu zu verbinden.",
                )
            return
        if stream.reconnect_failed:
            stream.reconnect_failed = False
            await self._session_clear(live, f"stream_lost_{stream.speaker}")
        device = getattr(stream.recorder, "device_name", "")
        text = f"{label} neu verbunden ({reason})" + (f": {device}" if device else "")
        log.info(text)
        at = stream.segmenter.position_s
        row = self._require_store().add_session_segment(live.id, at, at, text, speaker="system")
        await self.broadcast({"type": "session_segment", "session_id": live.id, "segment": row})
        await self.broadcast({"type": "notice", "text": text})

    async def _session_silence_check(self, live: "_LiveSession", now: float) -> None:
        stream = next((s for s in live.streams if s.speaker == "them"), None)
        if not stream:
            return
        level_at = getattr(stream.recorder, "level_at", 0.0)
        level_db = getattr(stream.recorder, "level_db", audio.SILENCE_DB)
        if level_at and now - level_at < 1.0 and level_db > SILENT_DB:
            live.desktop_loud_at = now
        silent_for = now - live.desktop_loud_at
        if silent_for >= DESKTOP_SILENT_WARN_S and not live.silence_warned:
            live.silence_warned = True
            device = getattr(stream.recorder, "device_name", "") or "unbekannt"
            await self._session_warn(
                live, "desktop_silent",
                f"Desktop-Audio seit {int(silent_for)} s stumm. Aufgenommen wird: {device}. "
                "Läuft der Ton über ein anderes Gerät, dieses in Windows als Standard-Ausgabe wählen.",
            )
        elif silent_for < DESKTOP_SILENT_WARN_S and live.silence_warned:
            live.silence_warned = False
            await self._session_clear(live, "desktop_silent")

    async def _session_level_loop(self, live: "_LiveSession") -> None:
        scalers = {s.speaker: audio.LevelScaler() for s in live.streams}
        while True:
            await asyncio.sleep(SESSION_LEVEL_INTERVAL_S)
            now = time.monotonic()
            levels = {}
            for stream in live.streams:
                fresh = now - getattr(stream.recorder, "level_at", 0.0) < 0.5
                db = getattr(stream.recorder, "level_db", audio.SILENCE_DB) if fresh else audio.SILENCE_DB
                levels[stream.speaker] = round(scalers[stream.speaker].scale(float(db)), 3) if fresh else 0.0
            await self.broadcast({
                "type": "session_levels", "session_id": live.id, "levels": levels,
                "lag_s": round(live.queued_s, 1), "elapsed_s": round(time.time() - live.started, 1),
            })

    # --- session data -----------------------------------------------------------
    def _stt_info(self) -> dict[str, Any]:
        t = self.transcriber
        if not t:
            return {"model": "", "device": "", "fallback": False}
        fallback = t.device == "cpu" and self.settings.get("device") in ("auto", "cuda")
        return {"model": t.model_name, "device": t.device, "fallback": fallback}

    async def api_stt_info(self) -> dict[str, Any]:
        return self._stt_info()

    def _session_payload(self, session_id: int) -> dict[str, Any]:
        store = self._require_store()
        session = store.get_session(session_id)
        files = _session_files(session)
        return {
            **session, "stt": self._stt_info(), "busy": session_id in self._jobs,
            "audio": {k: str(v) for k, v in files.items() if v.exists()},
        }

    async def _broadcast_session(self, session_id: int) -> None:
        await self.broadcast({"type": "session_status", "session": self._session_payload(session_id)})

    def _prune_session_audio(self, store: Store) -> None:
        for session_id, path in store.session_audio_paths_beyond(SESSION_KEEP_AUDIO):
            if session_id in self._jobs:
                continue
            for file in _audio_family(Path(path)):
                file.unlink(missing_ok=True)
            store.clear_session_audio_path(session_id)

    def _repair_session_audio(self) -> None:
        """WAV files of sessions cut off by a crash get valid headers again, so they open and can be re-run."""
        if not self.store:
            return
        for session in self.store.list_sessions(500):
            if session["status"] == "interrupted" and session.get("audio_path"):
                for file in _audio_family(Path(session["audio_path"])):
                    if file.exists() and audio.repair_wav(file):
                        log.info("WAV repariert: %s", file)

    async def api_session_list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        sessions = self._require_store().list_sessions(limit, offset)
        return [{**s, "busy": s["id"] in self._jobs} for s in sessions]

    async def api_session_get(self, id: int) -> dict[str, Any]:  # noqa: A002
        store = self._require_store()
        return {**self._session_payload(id), "segments": store.session_segments(id)}

    async def api_session_update_notes(self, id: int, notes: str) -> dict[str, Any]:  # noqa: A002
        store = self._require_store()
        store.update_session_notes(id, notes)
        return store.get_session(id)

    async def api_session_rename(self, id: int, title: str) -> dict[str, Any]:  # noqa: A002
        title = title.strip()
        if not title:
            raise ValueError("Der Titel darf nicht leer sein")
        self._require_store().update_session_title(id, title[:200])
        await self._broadcast_session(id)
        return self._session_payload(id)

    async def api_session_delete(self, id: int) -> None:  # noqa: A002
        if id == self.session_id:
            raise ValueError("Die laufende Sitzung kann nicht gelöscht werden")
        if id in self._jobs:
            raise ValueError("Die Sitzung wird gerade verarbeitet")
        path = self._require_store().delete_session(id)
        if path:
            for file in _audio_family(Path(path)):
                file.unlink(missing_ok=True)

    async def api_session_export(self, id: int, format: str = "md") -> dict[str, str]:  # noqa: A002
        store = self._require_store()
        session, segments = store.get_session(id), store.session_segments(id)
        if format == "md":
            return {"filename": export.filename(session, "md"), "content": export.to_markdown(session, segments)}
        if format == "txt":
            return {"filename": export.filename(session, "txt"), "content": export.to_text(session, segments)}
        raise ValueError(f"Unbekanntes Format: {format}")

    async def api_session_summarize(self, id: int) -> dict[str, Any]:  # noqa: A002
        store = self._require_store()
        if id == self.session_id:
            raise ValueError("Die laufende Sitzung kann noch nicht zusammengefasst werden")
        if not self.settings["llm"].get("enabled"):
            raise ValueError("Die KI-Zusammenfassung ist deaktiviert")
        text = " ".join(seg["text"] for seg in store.session_segments(id) if seg["speaker"] != "system")
        try:
            summary, items = await asyncio.to_thread(llm.summarize_session, text, self.settings["llm"])
        except Exception as exc:  # the transcript stays untouched, only the summary failed
            log.exception("Zusammenfassung fehlgeschlagen")
            raise ValueError(f"Zusammenfassung fehlgeschlagen: {exc}") from exc
        store.set_session_summary(id, summary, items)
        await self._broadcast_session(id)
        return self._session_payload(id)

    # --- re-run and import ------------------------------------------------------
    async def api_session_retranscribe(self, id: int) -> dict[str, Any]:  # noqa: A002
        """Transcribe a finished session again from its audio files, e.g. after a crash or with new terms."""
        store = self._require_store()
        if id == self.session_id:
            raise ValueError("Die laufende Sitzung kann nicht neu transkribiert werden")
        if id in self._jobs:
            raise ValueError("Die Sitzung wird schon verarbeitet")
        if not self.transcriber:
            raise ValueError("Bitte warte, bis Murmel bereit ist")
        session = store.get_session(id)
        tracks = _retranscribe_tracks(session)
        if not tracks:
            raise ValueError("Zu dieser Sitzung gibt es keine Audiodatei")
        self._start_job(session, tracks)
        return self._session_payload(id)

    async def api_session_import(self, path: str, title: str = "") -> dict[str, Any]:
        """A recording made elsewhere (OBS, Windows recorder) becomes a session with its own transcript."""
        store = self._require_store()
        if not self.transcriber or not self.account_dir:
            raise ValueError("Bitte warte, bis Murmel bereit ist")
        source_path = Path(path)
        if not source_path.is_file():
            raise ValueError("Datei nicht gefunden")
        started = source_path.stat().st_mtime
        name = title.strip() or source_path.stem
        session = store.create_session(name, started, self.settings["language"], source="import", status="processing")
        main = self.account_dir / "audio" / f"session-{session['id']}.wav"
        try:
            seconds = await asyncio.to_thread(_convert_to_wav, source_path, main)
        except Exception as exc:
            store.finish_session(session["id"], time.time(), "error")
            await self._broadcast_session(session["id"])
            raise ValueError(f"Datei konnte nicht gelesen werden: {exc}") from exc
        store.set_session_audio(session["id"], str(main))
        store.finish_session(session["id"], started + seconds, "processing")
        session = store.get_session(session["id"])
        self._start_job(session, [("them", main)])
        return self._session_payload(session["id"])

    def _start_job(self, session: dict[str, Any], tracks: list[tuple[str, Path]]) -> None:
        previous = session["status"] if session["status"] not in ("processing", "recording") else "done"
        self._jobs[session["id"]] = asyncio.create_task(self._run_job(session, tracks, previous))

    async def _run_job(self, session: dict[str, Any], tracks: list[tuple[str, Path]], previous: str) -> None:
        store = self._require_store()
        session_id = session["id"]
        terms = [t.strip() for t in (session.get("terms") or "").split(",") if t.strip()]
        ctx = _JobContext(session.get("language") or self.settings["language"], terms)
        store.set_session_status(session_id, "processing")
        await self._broadcast_session(session_id)
        try:
            total = 0.0
            for _speaker, path in tracks:
                await asyncio.to_thread(audio.repair_wav, path)
                total += await asyncio.to_thread(_wav_seconds, path)
            total = total or 1.0
            done = 0.0
            rows: list[tuple[str, float, float, str]] = []
            for speaker, path in tracks:
                segmenter = Segmenter()
                chunks = audio.read_wav_chunks(path)
                while True:
                    chunk = await asyncio.to_thread(next, chunks, None)
                    pieces = segmenter.feed(chunk) if chunk is not None else [p for p in [segmenter.flush()] if p]
                    for piece in pieces:
                        if piece.end_s - piece.start_s >= MIN_DURATION_S:
                            text = await asyncio.to_thread(self._transcribe_session_segment, ctx, piece.samples)
                            if text:
                                rows.append((speaker, piece.start_s, piece.end_s, text))
                    if chunk is None:
                        break
                    done += chunk.size / audio.SAMPLE_RATE
                    await self.broadcast({
                        "type": "session_progress", "session_id": session_id,
                        "progress": round(min(1.0, done / total), 3),
                    })
            rows.sort(key=lambda r: r[1])
            store.replace_session_segments(session_id, rows)
            store.set_session_status(session_id, "done")
        except Exception as exc:  # noqa: BLE001 - the old transcript is still there
            log.exception("Neu-Transkription fehlgeschlagen")
            store.set_session_status(session_id, previous)
            await self.broadcast({"type": "notice", "text": f"Neu-Transkription fehlgeschlagen: {exc}"})
        finally:
            self._jobs.pop(session_id, None)
        await self._broadcast_session(session_id)

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
