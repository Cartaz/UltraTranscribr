"""Independent live transcription sessions sharing one serialized backend."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from config.settings import AudioSource, Settings
from core.audio_capture import AudioCaptureThread
from core.audio_routing import PlaybackStream, PulseAudioRouter, StreamRouteLease
from core.buffer_manager import BufferManager
from core.event_bus import EventBus
from core.models import StatusEnum
from core.transcriber import TranscriberThread
from core.transcript_history import TranscriptHistoryStore
from core.whisper_backend import WhisperBackend

logger = logging.getLogger(__name__)
BackendInitializer = Callable[[Settings], None]
SinkResolver = Callable[[Optional[str], str], str]

_TERMINAL = {
    StatusEnum.STOPPED.value,
    StatusEnum.COMPLETED.value,
    StatusEnum.ERROR.value,
}


@dataclass
class TranscriptionSession:
    """Runtime state for one Live capture/transcription pipeline."""

    id: str
    source: str
    source_path: str
    sink_name: Optional[str]
    stream_id: Optional[int]
    settings: Settings
    buffer: BufferManager
    status: str = "starting"
    queue_wait_ms: float = 0.0
    queue_peak_ms: float = 0.0
    queue_samples: int = 0
    created_monotonic: float = field(default_factory=time.monotonic)
    capture: Optional[AudioCaptureThread] = None
    transcriber: Optional[TranscriberThread] = None
    route: Optional[StreamRouteLease] = None
    startup_thread: Optional[threading.Thread] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    terminal: bool = False
    cleanup_started: bool = False

    def snapshot(self) -> dict[str, Any]:
        capture_alive = bool(self.capture and self.capture.is_alive())
        transcriber_alive = bool(self.transcriber and self.transcriber.is_alive())
        return {
            "id": self.id,
            "status": self.status,
            "source": self.source,
            "source_path": self.source_path,
            "sink": self.sink_name,
            "stream_id": self.stream_id,
            "model": self.settings.model_size,
            "language": self.settings.language,
            "buffer_level": self.buffer.buffer_level,
            "queue_wait_ms": round(self.queue_wait_ms, 1),
            "queue_peak_ms": round(self.queue_peak_ms, 1),
            "queue_samples": self.queue_samples,
            "capture_running": capture_alive,
            "transcriber_running": transcriber_alive,
            "draining": not capture_alive and transcriber_alive and not self.terminal,
            "terminal": self.terminal,
        }


class LiveSessionManager:
    """Own multiple Live pipelines while sharing one WhisperBackend."""

    def __init__(
        self,
        *,
        backend: WhisperBackend,
        router: PulseAudioRouter,
        history: TranscriptHistoryStore,
        backend_initializer: BackendInitializer,
        sink_resolver: SinkResolver,
    ) -> None:
        self._backend = backend
        self._router = router
        self._history = history
        self._backend_initializer = backend_initializer
        self._sink_resolver = sink_resolver
        self._bus = EventBus()
        self._lock = threading.RLock()
        self._sessions: dict[str, TranscriptionSession] = {}

    def create_session(
        self,
        *,
        settings: Settings,
        audio_source: str,
        sink_name: Optional[str] = None,
        language: Optional[str] = None,
        stream_id: Optional[int] = None,
    ) -> dict[str, Any]:
        source = audio_source
        lang = language or settings.language
        session_settings = settings.with_(language=lang)
        selected_stream: Optional[PlaybackStream] = None

        if source == AudioSource.APPLICATION.value:
            if stream_id is None:
                raise RuntimeError("Seleziona uno stream applicazione da trascrivere")
            selected_stream = self._router.get_stream(int(stream_id))
            resolved_sink = None
            source_path = selected_stream.display_name
        else:
            resolved_sink = self._sink_resolver(sink_name, source)
            source_path = resolved_sink

        session_id = self._history.create_session(
            kind="live",
            model=session_settings.model_size,
            language=session_settings.language,
            source=source,
            source_path=source_path or "",
            status="starting",
        )
        session = TranscriptionSession(
            id=session_id,
            source=source,
            source_path=source_path or "",
            sink_name=resolved_sink,
            stream_id=int(stream_id) if stream_id is not None else None,
            settings=session_settings,
            buffer=BufferManager(warn_threshold=session_settings.buffer_warn_threshold),
        )
        with self._lock:
            self._sessions[session_id] = session
        self._emit("live_session_created", session.snapshot())

        startup = threading.Thread(
            target=self._start_session,
            args=(session, selected_stream),
            daemon=True,
            name=f"LiveSessionStartup-{session_id}",
        )
        session.startup_thread = startup
        startup.start()
        return session.snapshot()

    def list_sessions(self, *, include_text: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            sessions = list(self._sessions.values())
        result: list[dict[str, Any]] = []
        for session in sessions:
            snapshot = session.snapshot()
            if include_text:
                record = self._history.get_session(session.id)
                snapshot["text"] = str((record or {}).get("text") or "")
            result.append(snapshot)
        result.sort(key=lambda item: item["id"])
        return result

    def get_session(self, session_id: str, *, include_text: bool = False) -> Optional[dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return None
        snapshot = session.snapshot()
        if include_text:
            record = self._history.get_session(session.id)
            snapshot["text"] = str((record or {}).get("text") or "")
        return snapshot

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for session in self._sessions.values() if not session.terminal)

    def has_active_sessions(self) -> bool:
        return self.active_count() > 0

    def stop_session(self, session_id: str, *, drain: bool = False) -> bool:
        session = self._require_session(session_id)
        with self._lock:
            if session.terminal:
                return False
            session.cancel_event.set()
            capture = session.capture
            transcriber = session.transcriber
            route = session.route
            session.route = None

        if capture:
            capture.stop()
            if capture is not threading.current_thread() and capture.is_alive():
                capture.join(timeout=5.0)
        if route:
            route.close()

        if drain and transcriber and transcriber.is_alive():
            session.buffer.close_input()
            self._set_status(session, "draining")
            self._emit("live_session_route_status", {"session_id": session.id, "status": "restored"})
            return True

        if transcriber:
            transcriber.stop()
        session.buffer.close_input()
        self._finish(session, StatusEnum.STOPPED.value)
        self._emit("live_session_route_status", {"session_id": session.id, "status": "restored"})
        return True

    def stop_all(self, *, drain: bool = False) -> None:
        with self._lock:
            ids = [session.id for session in self._sessions.values() if not session.terminal]
        for session_id in ids:
            try:
                self.stop_session(session_id, drain=drain)
            except Exception:
                logger.exception("Arresto sessione %s fallito", session_id)

    def remove_session(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if not session.terminal:
                raise RuntimeError("Ferma la sessione prima di rimuoverla dalla vista")
            self._sessions.pop(session_id, None)
        self._emit("live_session_removed", {"session_id": session_id})
        return True

    def shutdown(self) -> None:
        self.stop_all(drain=False)
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            startup = session.startup_thread
            if startup and startup.is_alive() and startup is not threading.current_thread():
                startup.join(timeout=3.0)
            transcriber = session.transcriber
            if transcriber and transcriber.is_alive() and transcriber is not threading.current_thread():
                transcriber.join(timeout=1.0)
            if not transcriber or not transcriber.is_alive():
                session.buffer.close()

    def _start_session(
        self,
        session: TranscriptionSession,
        selected_stream: Optional[PlaybackStream],
    ) -> None:
        route: Optional[StreamRouteLease] = None
        try:
            self._set_status(session, "preparing_backend")
            self._backend_initializer(session.settings)
            if session.cancel_event.is_set():
                return

            capture_sink = session.sink_name
            if session.source == AudioSource.APPLICATION.value:
                assert session.stream_id is not None
                self._set_status(session, "isolating")
                route = self._router.isolate_stream(
                    session.stream_id,
                    status_callback=lambda payload: self._route_event(session, payload),
                )
                capture_sink = route.monitor_name
                session.sink_name = capture_sink
                session.route = route

            if session.cancel_event.is_set():
                if route:
                    route.close()
                    session.route = None
                return

            callback = lambda event, payload: self._worker_event(session, event, payload)
            capture = AudioCaptureThread(
                session.buffer,
                session.settings,
                capture_sink,
                session.source,
                session_id=session.id,
                event_sink=callback,
            )
            transcriber = TranscriberThread(
                session.buffer,
                self._backend,
                session.settings,
                session_id=session.id,
                event_sink=callback,
            )
            with self._lock:
                if session.cancel_event.is_set() or session.terminal:
                    if route:
                        route.close()
                        session.route = None
                    return
                session.capture = capture
                session.transcriber = transcriber
            capture.start()
            transcriber.start()
            self._set_status(session, StatusEnum.RUNNING.value)
        except Exception as exc:
            logger.exception("Avvio sessione Live %s fallito", session.id)
            if route:
                try:
                    route.close()
                except Exception:
                    logger.exception("Cleanup route sessione %s fallito", session.id)
                session.route = None
            if not session.terminal:
                self._error(session, str(exc))

    def _worker_event(self, session: TranscriptionSession, event: str, payload: Any) -> None:
        if event == "transcriber_buffer_level":
            self._emit(
                "live_session_buffer_level",
                {"session_id": session.id, "level": int(payload or 0)},
            )
            return
        if event == "transcriber_queue_wait":
            wait_ms = max(0.0, float(payload or 0.0))
            with self._lock:
                session.queue_wait_ms = wait_ms
                session.queue_peak_ms = max(session.queue_peak_ms, wait_ms)
                session.queue_samples += 1
                peak = session.queue_peak_ms
            self._emit(
                "live_session_queue_wait",
                {
                    "session_id": session.id,
                    "wait_ms": round(wait_ms, 1),
                    "peak_ms": round(peak, 1),
                },
            )
            return
        if event == "transcriber_new_text":
            text = str(payload or "").strip()
            if text:
                try:
                    self._history.append_text(session.id, text)
                except Exception as exc:
                    logger.exception("Autosave sessione %s fallito", session.id)
                    self._emit("history_error", str(exc))
                self._emit(
                    "live_session_text",
                    {"session_id": session.id, "text": text},
                )
            return
        if event == "recovery_audio_saved":
            self._emit(
                "recovery_audio_saved",
                {"session_id": session.id, "path": str(payload or "")},
            )
            return
        if event == "transcriber_error":
            self._error(session, str(payload or "Errore trascrizione"))
            return
        if event == "transcriber_drained":
            self._finish(session, StatusEnum.COMPLETED.value)
            return
        if event == "transcriber_status_changed":
            status = str(payload or "")
            if status == StatusEnum.ERROR.value:
                return
            if status == StatusEnum.STOPPED.value:
                if not session.terminal and session.status == "draining":
                    self._finish(session, StatusEnum.COMPLETED.value)
                self._defer_buffer_close(session)
                return
            if not session.terminal and status:
                self._set_status(session, status)

    def _route_event(self, session: TranscriptionSession, payload: dict[str, Any]) -> None:
        enriched = dict(payload)
        enriched["session_id"] = session.id
        stream = enriched.get("stream")
        if isinstance(stream, dict) and stream.get("display_name"):
            session.source_path = str(stream["display_name"])
        self._emit("live_session_route_status", enriched)

    def _set_status(self, session: TranscriptionSession, status: str) -> None:
        with self._lock:
            if session.terminal:
                return
            session.status = str(status)
            snapshot = session.snapshot()
        try:
            self._history.set_status(session.id, session.status)
        except Exception as exc:
            logger.exception("Stato cronologia sessione %s fallito", session.id)
            self._emit("history_error", str(exc))
        self._emit("live_session_updated", snapshot)

    def _error(self, session: TranscriptionSession, error: str) -> None:
        capture = session.capture
        route = session.route
        if capture and capture.is_alive():
            capture.stop()
        if route:
            try:
                route.close()
            except Exception:
                logger.exception("Cleanup route dopo errore fallito")
            session.route = None
        self._finish(session, StatusEnum.ERROR.value)
        self._emit(
            "live_session_error",
            {"session_id": session.id, "error": error},
        )

    def _finish(self, session: TranscriptionSession, status: str) -> None:
        with self._lock:
            if session.terminal:
                return
            session.status = str(status)
            session.terminal = True
            snapshot = session.snapshot()
        try:
            self._history.set_status(session.id, session.status, terminal=True)
        except Exception as exc:
            logger.exception("Chiusura cronologia sessione %s fallita", session.id)
            self._emit("history_error", str(exc))
        self._emit("live_session_updated", snapshot)
        self._emit("history_changed", session.id)
        self._defer_buffer_close(session)

    def _defer_buffer_close(self, session: TranscriptionSession) -> None:
        with self._lock:
            if session.cleanup_started:
                return
            session.cleanup_started = True
            transcriber = session.transcriber

        def cleanup() -> None:
            if transcriber and transcriber.is_alive() and transcriber is not threading.current_thread():
                transcriber.join()
            session.buffer.close()

        threading.Thread(
            target=cleanup,
            daemon=True,
            name=f"LiveSessionCleanup-{session.id}",
        ).start()

    def _require_session(self, session_id: str) -> TranscriptionSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"sessione Live non trovata: {session_id}")
        return session

    def _emit(self, event: str, payload: Any = None) -> None:
        self._bus.emit(event, payload)
