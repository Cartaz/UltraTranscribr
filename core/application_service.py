"""Application-level workflows exposed to presentation adapters.

This module owns coordination rules that must not leak into Qt/WebChannel code:
workflow exclusivity, background execution, settings/backend transitions, history
naming and artifact cleanup.  The UI bridge only validates/serializes values and
invokes this service.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from config.settings import AudioSource, ModelSize, Settings
from core.app_controller import AppController
from core.audio_diagnostics import build_audio_diagnostics
from core.event_bus import EventBus
from core.history_postprocess import generate_history_postprocess
from core.session_names import SessionNameStore
from core.session_recordings import delete_recording, recording_info
from core.transcript_postprocess import profile_choices

logger = logging.getLogger(__name__)


class ApplicationService:
    """Deep application boundary used by desktop presentation adapters."""

    _BACKEND_SETTING_KEYS = {
        "model_size",
        "beam_size",
        "vad_filter",
        "vad_min_silence_ms",
        "server_port",
        "gpu_layers",
        "compute_type",
        "backend_instances",
    }

    def __init__(self, controller: AppController) -> None:
        self.controller = controller
        self.file_batch = controller.file_batch
        self.meeting = controller.meeting
        self._session_names = SessionNameStore()
        self._bus = EventBus()

    # ------------------------------------------------------------------
    # Background execution and startup
    # ------------------------------------------------------------------
    def submit(
        self,
        name: str,
        operation: Callable[[], None],
        error_event: str,
    ) -> None:
        """Run potentially blocking application work outside the Qt GUI thread."""

        def worker() -> None:
            try:
                operation()
            except Exception as exc:
                logger.exception("Operazione applicativa '%s' fallita", name)
                self._bus.emit(error_event, str(exc))

        threading.Thread(
            target=worker,
            daemon=True,
            name=f"Application-{name}",
        ).start()

    def preload_model_if_requested(self) -> None:
        settings = self.controller.settings
        if not settings.preload_model:
            return
        selected = settings.model_size
        installed = any(
            str(item.get("id")) == selected and bool(item.get("installed"))
            for item in self.controller.list_models()
        )
        if not installed:
            logger.info("Preload saltato: modello %s non installato", selected)
            return
        self.submit(
            "preload-model",
            self.controller.ensure_backend_started,
            "backend_preload_error",
        )

    # ------------------------------------------------------------------
    # Snapshot and settings
    # ------------------------------------------------------------------
    def bootstrap_snapshot(self) -> dict[str, Any]:
        discovery = self.controller.audio_discovery_snapshot()
        self.controller.request_audio_discovery()
        sessions = self.controller.list_live_sessions(include_text=True)
        return {
            "settings": asdict(self.controller.settings),
            "modelChoices": ModelSize.choices(),
            "models": self.controller.list_models(),
            "audioSources": AudioSource.choices(),
            "devices": discovery["devices"],
            "playbackStreams": discovery["streams"],
            "liveSessions": sessions,
            "fileQueue": self.file_batch.list_jobs(),
            "postprocessProfiles": profile_choices(),
            "meetingRuntime": self.meeting.snapshot(),
            "diarizationModels": self.meeting.models.status(),
            "runtime": {
                "liveSessionCount": sum(
                    1 for session in sessions if not bool(session.get("terminal"))
                ),
                "liveRunning": self.controller.is_running(),
                "liveDraining": self.controller.is_draining(),
                "fileRunning": self.controller.is_file_transcribing(),
                "backendRunning": self.controller.backend.is_running,
                "bufferLevel": self.controller.buffer.buffer_level,
                "meetingBusy": self.meeting.is_busy(),
            },
        }

    @staticmethod
    def settings_defaults() -> dict[str, Any]:
        return asdict(Settings())

    def apply_settings(self, overrides: dict[str, Any]) -> Settings:
        if self.meeting.is_busy():
            raise RuntimeError("Termina la riunione prima di modificare le impostazioni")
        before = self.controller.settings
        backend_changed = any(
            key in overrides and overrides[key] != getattr(before, key, None)
            for key in self._BACKEND_SETTING_KEYS
        )
        if backend_changed and (
            self.controller.active_live_count() > 0 or self.controller.is_file_busy()
        ):
            raise RuntimeError(
                "Ferma le trascrizioni attive prima di modificare il backend"
            )
        self.controller.update_settings(**overrides)
        current = self.controller.settings
        if backend_changed:
            if self.controller.backend.is_running:
                self.controller.stop_backend()
            self.controller.backend.reconfigure(current)
        return current

    # ------------------------------------------------------------------
    # Workflow policy
    # ------------------------------------------------------------------
    def start_live(
        self,
        *,
        sink_name: str | None,
        audio_source: str,
        language: str,
        stream_id: int | None,
        record_audio: bool,
    ) -> None:
        def operation() -> None:
            if self.meeting.is_busy():
                raise RuntimeError(
                    "Termina la riunione prima di avviare una sessione Live"
                )
            if self.controller.is_file_busy():
                raise RuntimeError("Ferma la trascrizione File prima di avviare Live")
            self.controller.start_live_session(
                sink_name=sink_name,
                audio_source=audio_source,
                language=language,
                stream_id=stream_id,
                record_audio=record_audio,
            )

        self.submit("start-live", operation, "live_session_start_error")

    def stop_live(self, session_id: str, *, drain: bool) -> None:
        self.submit(
            f"{'drain' if drain else 'stop'}-live-{session_id}",
            lambda: self.controller.stop_live_session(session_id, drain=drain),
            "live_session_action_error",
        )

    def remove_live(self, session_id: str) -> None:
        self.submit(
            f"remove-live-{session_id}",
            lambda: self.controller.remove_live_session(session_id),
            "live_session_action_error",
        )

    def stop_all_live(self, *, drain: bool) -> None:
        self.submit(
            "drain-all-live" if drain else "stop-all-live",
            lambda: self.controller.stop_all_live_sessions(drain=drain),
            "live_session_action_error",
        )

    def start_file(
        self,
        path: str,
        *,
        language: str,
        model_size: str,
        song_mode: bool,
        isolate_vocals: bool,
    ) -> None:
        if self.meeting.is_busy():
            raise RuntimeError(
                "Termina la riunione prima di avviare una trascrizione File"
            )
        self.controller.start_file_transcription(
            path,
            language=language,
            model_size=model_size,
            song_mode=song_mode,
            isolate_vocals_flag=bool(isolate_vocals and song_mode),
        )

    def stop_file(self) -> None:
        self.submit(
            "stop-file",
            self.controller.stop_file_transcription,
            "file_transcriber_error",
        )

    def enqueue_files(
        self,
        paths: list[str],
        *,
        language: str,
        model_size: str,
        song_mode: bool,
        isolate_vocals: bool,
    ) -> list[dict[str, Any]]:
        if self.meeting.is_busy():
            raise RuntimeError("Termina la riunione prima di accodare file")
        return self.file_batch.enqueue(
            paths,
            language=language,
            model_size=model_size,
            song_mode=song_mode,
            isolate_vocals=isolate_vocals,
        )

    def batch_busy(self) -> bool:
        return any(
            str(job.get("status")) in {"queued", "starting", "running"}
            for job in self.file_batch.list_jobs()
        )

    def start_meeting(
        self,
        *,
        microphone: str | None,
        language: str | None,
        num_speakers: int,
    ) -> dict[str, Any]:
        if self.batch_busy():
            raise RuntimeError(
                "Annulla o completa la coda File prima di avviare una riunione"
            )
        return self.meeting.start(
            microphone=microphone,
            language=language,
            num_speakers=num_speakers,
        )

    def require_meeting_idle(self, action: str) -> None:
        if self.meeting.is_busy():
            raise RuntimeError(f"Termina la riunione prima di {action}")

    def download_model(self, model_size: str) -> None:
        self.require_meeting_idle("gestire i modelli")
        self.controller._require_idle_for_model_operation()
        self.submit(
            f"download-model-{model_size}",
            lambda: self.controller.download_model(model_size),
            "model_download_error",
        )

    def delete_model(self, model_size: str) -> None:
        self.require_meeting_idle("gestire i modelli")
        self.controller._require_idle_for_model_operation()
        self.submit(
            f"delete-model-{model_size}",
            lambda: self.controller.delete_model(model_size),
            "model_delete_error",
        )

    # ------------------------------------------------------------------
    # History, names and recordings
    # ------------------------------------------------------------------
    def list_history(self, limit: int) -> list[dict[str, Any]]:
        return self._session_names.apply_many(self.controller.list_history(limit))

    def search_history(self, query: str, limit: int) -> list[dict[str, Any]]:
        self.controller.prune_history()
        base = self.controller.history.search(query, limit)
        by_id = {str(item.get("id")): item for item in base}
        name_ids = self._session_names.matching_ids(query)
        if name_ids and len(by_id) < limit:
            for item in self.controller.history.list_recent(500):
                session_id = str(item.get("id") or "")
                if session_id in name_ids and session_id not in by_id:
                    by_id[session_id] = item
                    if len(by_id) >= limit:
                        break
        return self._session_names.apply_many(list(by_id.values())[:limit])

    def get_history_session(self, session_id: str) -> dict[str, Any] | None:
        session = self.controller.get_history_session(session_id)
        if session and session.get("kind") == "meeting":
            session = self.meeting.get(session_id) or session
        return self._session_names.apply(session)

    def rename_history_session(self, session_id: str, name: str) -> str:
        if not self.controller.get_history_session(session_id):
            raise KeyError("sessione non trovata")
        cleaned = self._session_names.set(session_id, name)
        self._bus.emit("history_changed", session_id)
        return cleaned

    def generate_postprocess(self, session_id: str, profile: str) -> dict[str, Any]:
        return generate_history_postprocess(self.controller, session_id, profile)

    def export_history_format(
        self,
        session_id: str,
        target: str,
        format_name: str,
        profile: str,
    ) -> str:
        session = self.controller.get_history_session(session_id)
        if not session:
            raise KeyError("sessione non trovata")
        if session.get("kind") == "meeting":
            return str(self.meeting.store.export(session_id, target, format_name))
        return str(
            self.controller.history.export_session(
                session_id,
                target,
                format_name=format_name,
                profile=profile,
            )
        )

    def delete_history_session(self, session_id: str) -> bool:
        session = self.controller.get_history_session(session_id)
        if session and session.get("kind") == "meeting":
            current = self.meeting.snapshot()
            if current and current.get("id") == session_id and self.meeting.is_busy():
                raise RuntimeError("Termina la riunione prima di eliminarla")
        deleted = self.controller.delete_history_session(session_id)
        if not deleted:
            return False
        if session and session.get("kind") == "meeting":
            try:
                self.meeting.store.delete_audio(session_id)
            except Exception as exc:
                logger.warning("Rimozione audio meeting %s fallita: %s", session_id, exc)
            (self.meeting.store.root / f"{session_id}.json").unlink(missing_ok=True)
        elif session and session.get("kind") == "live" and session.get("source") == "microphone":
            delete_recording(session_id)
        self._session_names.delete(session_id)
        self._bus.emit("history_changed", session_id)
        return True

    def session_recording_info(self, session_id: str) -> dict[str, Any]:
        session = self.controller.get_history_session(session_id)
        if not session or session.get("kind") != "live" or session.get("source") != "microphone":
            return {"exists": False, "session_id": session_id}
        return recording_info(session_id)

    def delete_session_recording(self, session_id: str) -> bool:
        runtime = self.controller.get_live_session(session_id)
        if runtime is not None and not bool(runtime.get("terminal")):
            raise RuntimeError(
                "Ferma la sessione Live prima di eliminare la registrazione"
            )
        session = self.controller.get_history_session(session_id)
        if not session or session.get("kind") != "live" or session.get("source") != "microphone":
            raise ValueError("La sessione non è una Live da microfono")
        deleted = delete_recording(session_id)
        self._bus.emit("history_changed", session_id)
        return deleted

    def run_audio_diagnostics(self) -> None:
        self.submit(
            "audio-diagnostics",
            lambda: self._bus.emit(
                "audio_diagnostics",
                build_audio_diagnostics(self.controller),
            ),
            "audio_diagnostics_error",
        )
