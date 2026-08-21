"""Multi-session WebChannel API layered on the existing presentation bridge."""
from __future__ import annotations

import json
import logging

from PySide6.QtCore import Slot

from config.settings import AudioSource
from ui.bridge import BackendBridge

logger = logging.getLogger(__name__)


class MultiSessionBackendBridge(BackendBridge):
    """Expose session-scoped Live operations while retaining File/settings APIs."""

    _EVENTS = BackendBridge._EVENTS + (
        "live_session_created",
        "live_session_updated",
        "live_session_buffer_level",
        "live_session_queue_wait",
        "live_session_text",
        "live_session_error",
        "live_session_route_status",
        "live_session_removed",
    )

    @Slot(result=str)
    def getBootstrap(self) -> str:
        payload = json.loads(super().getBootstrap())
        sessions = self._controller.list_live_sessions(include_text=True)
        payload["liveSessions"] = sessions
        runtime = payload.setdefault("runtime", {})
        runtime["liveSessionCount"] = sum(
            1 for session in sessions if not bool(session.get("terminal"))
        )
        runtime["liveRunning"] = self._controller.is_running()
        runtime["liveDraining"] = self._controller.is_draining()
        runtime["bufferLevel"] = self._controller.buffer.buffer_level
        return json.dumps(payload, ensure_ascii=False, default=str)

    @Slot(result=str)
    def listLiveSessions(self) -> str:
        return json.dumps(
            self._controller.list_live_sessions(include_text=True),
            ensure_ascii=False,
            default=str,
        )

    @Slot(str, str, str)
    def startLive(
        self,
        audio_source: str,
        selected_input: str,
        language: str,
    ) -> None:
        source = (
            audio_source
            if audio_source in AudioSource.choices()
            else self._controller.settings.audio_source
        )
        selection = selected_input.strip()
        lang = language.strip() or self._controller.settings.language
        sink = None
        stream_id = None
        if source == AudioSource.APPLICATION.value:
            if not selection:
                self._emit_event(
                    "live_session_start_error",
                    "Seleziona uno stream applicazione prima di avviare la sessione",
                )
                return
            try:
                stream_id = int(selection)
            except ValueError:
                self._emit_event(
                    "live_session_start_error",
                    "Identificatore dello stream applicazione non valido",
                )
                return
        else:
            sink = selection or None

        def operation() -> None:
            self._prepare_backend_for_selected_model()
            self._controller.start_live_session(
                sink_name=sink,
                audio_source=source,
                language=lang,
                stream_id=stream_id,
            )

        self._run_async(
            "start-live-session",
            operation,
            "live_session_start_error",
        )

    @Slot(str)
    def stopLiveSession(self, session_id: str) -> None:
        self._run_async(
            f"stop-live-{session_id}",
            lambda: self._controller.stop_live_session(session_id, drain=False),
            "live_session_action_error",
        )

    @Slot(str)
    def drainLiveSession(self, session_id: str) -> None:
        self._run_async(
            f"drain-live-{session_id}",
            lambda: self._controller.stop_live_session(session_id, drain=True),
            "live_session_action_error",
        )

    @Slot(str)
    def removeLiveSession(self, session_id: str) -> None:
        self._run_async(
            f"remove-live-{session_id}",
            lambda: self._controller.remove_live_session(session_id),
            "live_session_action_error",
        )

    @Slot()
    def stopAllLive(self) -> None:
        self._run_async(
            "stop-all-live",
            lambda: self._controller.stop_all_live_sessions(drain=False),
            "live_session_action_error",
        )

    @Slot()
    def drainAllLive(self) -> None:
        self._run_async(
            "drain-all-live",
            lambda: self._controller.stop_all_live_sessions(drain=True),
            "live_session_action_error",
        )

    # Legacy shell/tray operations now act on all Live sessions.
    @Slot()
    def stopLive(self) -> None:
        self.stopAllLive()

    @Slot()
    def stopListening(self) -> None:
        self.drainAllLive()
