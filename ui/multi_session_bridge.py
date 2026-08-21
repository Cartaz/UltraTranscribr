"""Multi-session WebChannel API layered on the existing presentation bridge."""
from __future__ import annotations

import json
import logging
from typing import Any

from PySide6.QtCore import Slot

from config.settings import AudioSource
from core.sink_finder import debug_dump, find_source, list_available_devices
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

    @Slot(str, str, result=str)
    def probeAudioSource(self, audio_source: str, selected_input: str) -> str:
        """Return actionable availability for the currently selected Live source."""
        source = (
            audio_source
            if audio_source in AudioSource.choices()
            else self._controller.settings.audio_source
        )
        selection = str(selected_input or "").strip()
        try:
            status = self._probe_audio_source(source, selection)
        except Exception as exc:
            logger.warning("Probe sorgente audio fallito: %s", exc)
            status = {
                "source": source,
                "status": "disconnected",
                "label": "Non disponibile",
                "detail": str(exc),
            }
        return json.dumps(status, ensure_ascii=False, default=str)

    def _probe_audio_source(self, source: str, selection: str) -> dict[str, Any]:
        if source == AudioSource.APPLICATION.value:
            streams = self._controller.list_playback_streams()
            if selection:
                try:
                    stream_id = int(selection)
                except ValueError:
                    stream_id = -1
                selected = next(
                    (item for item in streams if int(item.get("id", -1)) == stream_id),
                    None,
                )
                if selected is None:
                    return {
                        "source": source,
                        "status": "disconnected",
                        "label": "Stream disconnesso",
                        "detail": "Lo stream selezionato non è più presente.",
                        "streams": len(streams),
                    }
                playing = str(selected.get("state") or "").casefold() != "paused"
                return {
                    "source": source,
                    "status": "playing" if playing else "available",
                    "label": "In riproduzione" if playing else "Disponibile · in pausa",
                    "detail": selected.get("display_name") or f"Stream #{stream_id}",
                    "stream": selected,
                    "streams": len(streams),
                }
            if streams:
                return {
                    "source": source,
                    "status": "available",
                    "label": f"Disponibili {len(streams)} stream",
                    "detail": "Seleziona lo stream da isolare.",
                    "streams": len(streams),
                }
            return {
                "source": source,
                "status": "disconnected",
                "label": "Nessuno stream",
                "detail": "Avvia la riproduzione in un'applicazione e aggiorna l'elenco.",
                "streams": 0,
            }

        devices = list_available_devices()
        key = "is_monitor" if source == AudioSource.SYSTEM.value else "is_mic"
        candidates = [item for item in devices if bool(item.get(key))]
        if selection:
            selected = next(
                (item for item in candidates if str(item.get("name") or "") == selection),
                None,
            )
            if selected is None:
                return {
                    "source": source,
                    "status": "disconnected",
                    "label": "Dispositivo non disponibile",
                    "detail": selection,
                    "devices": len(candidates),
                }
            return {
                "source": source,
                "status": "available",
                "label": "Disponibile",
                "detail": str(selected.get("name") or selection),
                "device": selected,
                "devices": len(candidates),
            }

        automatic = find_source(self._controller.settings, audio_source=source)
        if automatic:
            return {
                "source": source,
                "status": "available",
                "label": "Disponibile · automatico",
                "detail": automatic,
                "devices": len(candidates),
            }
        label = (
            "Audio di sistema non disponibile"
            if source == AudioSource.SYSTEM.value
            else "Microfono non disponibile"
        )
        return {
            "source": source,
            "status": "disconnected",
            "label": label,
            "detail": "Nessun ingresso compatibile rilevato.",
            "devices": len(candidates),
        }

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

    @Slot()
    def runAudioDiagnostics(self) -> None:
        """Include devices, streams and active per-session routing in one report."""
        def operation() -> None:
            report = debug_dump()
            report += "\n\n=== playback streams ==="
            try:
                streams = self._controller.list_playback_streams()
            except Exception as exc:
                report += f"\n  Errore: {exc}"
            else:
                if not streams:
                    report += "\n  nessuno stream attivo"
                for stream in streams:
                    report += (
                        f"\n  [#{stream.get('id')}] "
                        f"{stream.get('display_name') or 'stream'}"
                        f"\n      pid={stream.get('process_id') or '-'} "
                        f"binary={stream.get('process_binary') or '-'} "
                        f"sink={stream.get('sink_name') or '-'} "
                        f"state={stream.get('state') or '-'}"
                    )

            report += "\n\n=== UltraTranscribr live routing ==="
            sessions = self._controller.list_live_sessions(include_text=False)
            if not sessions:
                report += "\n  nessuna sessione Live"
            for session in sessions:
                if session.get("source") == AudioSource.APPLICATION.value:
                    routing = "restored" if session.get("terminal") else "isolated"
                else:
                    routing = "direct"
                report += (
                    f"\n  [{session.get('id')}] source={session.get('source')} "
                    f"status={session.get('status')} routing={routing}"
                    f"\n      input={session.get('source_path') or '-'} "
                    f"capture={session.get('sink') or '-'} "
                    f"buffer={session.get('buffer_level', 0)}% "
                    f"queue_wait={session.get('queue_wait_ms', 0)}ms"
                )
            self._emit_event("audio_diagnostics", report)

        self._run_async(
            "audio-diagnostics",
            operation,
            "audio_diagnostics_error",
        )

    # Legacy shell/tray operations now act on all Live sessions.
    @Slot()
    def stopLive(self) -> None:
        self.stopAllLive()

    @Slot()
    def stopListening(self) -> None:
        self.drainAllLive()
