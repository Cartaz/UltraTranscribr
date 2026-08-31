"""Application-level workflows exposed to presentation adapters.

This module owns coordination rules that must not leak into Qt/WebChannel code:
workflow exclusivity, background execution, settings/backend transitions, history
naming and artifact cleanup. The UI bridge only validates/serializes values and
invokes this service.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from config.constants import AppMeta
from config.settings import AudioSource, ModelSize, Settings
from core.app_controller import AppController
from core.audio_diagnostics import build_audio_diagnostics
from core.background_tasks import BackgroundTaskGroup
from core.event_bus import EventBus
from core.history_postprocess import generate_history_postprocess
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
        self.controller.history.migrate_legacy_session_names()
        self._bus = EventBus()
        self._tasks = BackgroundTaskGroup("Application", join_timeout=10.0)
        self._subscriptions: list[tuple[str, Callable[[Any], None]]] = []
        self._closed = False

    def close(self) -> None:
        """Release application-boundary subscriptions and owned work exactly once."""
        if self._closed:
            return
        self._closed = True
        for event, handler in reversed(self._subscriptions):
            try:
                self.controller.unsubscribe(event, handler)
            except Exception:
                logger.exception("Disiscrizione evento applicativo '%s' fallita", event)
        self._subscriptions.clear()
        self._tasks.close()

    def subscribe(self, event: str, handler: Callable[[Any], None]) -> None:
        if self._closed:
            raise RuntimeError("application service chiuso")
        self.controller.subscribe(event, handler)
        self._subscriptions.append((event, handler))

    def unsubscribe(self, event: str, handler: Callable[[Any], None]) -> None:
        self.controller.unsubscribe(event, handler)
        subscription = (event, handler)
        if subscription in self._subscriptions:
            self._subscriptions.remove(subscription)

    def desktop_state(self) -> dict[str, Any]:
        """Return the small native-shell state surface without leaking AppController."""
        settings = self.controller.settings
        return {
            "window_width": settings.window_width,
            "window_height": settings.window_height,
            "audio_source": settings.audio_source,
            "sink_name": settings.sink_name,
            "language": settings.language,
            "live_active": self.controller.active_live_count() > 0,
        }

    def persist_window_geometry(self, width: int, height: int) -> None:
        """Persist native window geometry independently from workflow settings rules."""
        settings = self.controller.settings
        if settings.window_width == width and settings.window_height == height:
            return
        self.controller.update_settings(window_width=width, window_height=height)

    def live_active(self) -> bool:
        """Expose the tray's coarse runtime indicator without leaking controller state."""
        return self.controller.active_live_count() > 0

    def dictation_insertion_mode(self) -> str:
        """Return the canonical insertion policy for the next dictation session."""
        return self.controller.settings.dictation_insertion_mode

    def dictation_shortcut_pressed(self) -> None:
        """Forward one native global-shortcut press into the canonical dictation state."""
        self.controller.dictation_shortcut_pressed()

    def dictation_shortcut_released(self) -> None:
        """Forward one native global-shortcut release into the canonical dictation state."""
        self.controller.dictation_shortcut_released()

    def dictation_text_inserted(self, text: str) -> None:
        """Report text inserted by the native adapter for dictation telemetry."""
        self.controller.dictation_text_inserted(text)

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

        self._tasks.start(name, worker)

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

    def filter_settings_overrides(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = set(self.controller.settings.__dataclass_fields__)
        return {key: value for key, value in payload.items() if key in allowed}

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

    def refresh_devices(self, audio_source: str) -> list[dict[str, Any]]:
        source = (
            audio_source
            if audio_source in AudioSource.choices()
            else self.controller.settings.audio_source
        )
        if source == AudioSource.APPLICATION.value:
            return []
        self.controller.request_audio_discovery(devices=True, streams=False)
        devices = self.controller.audio_discovery_snapshot()["devices"]
        key = "is_monitor" if source == AudioSource.SYSTEM.value else "is_mic"
        return [device for device in devices if bool(device.get(key))]

    def list_playback_streams(self) -> list[dict[str, Any]]:
        self.controller.request_audio_discovery(devices=False, streams=True)
        return self.controller.audio_discovery_snapshot()["streams"]

    def probe_audio_source(self, audio_source: str, selected_input: str) -> dict[str, Any]:
        source = (
            audio_source
            if audio_source in AudioSource.choices()
            else self.controller.settings.audio_source
        )
        selection = str(selected_input or "").strip()
        status = self.controller.cached_audio_source_health(source, selection)
        self.controller.request_audio_source_probe(source, selection)
        return status

    def start_live(
        self,
        audio_source: str,
        selected_input: str,
        language: str,
        record_audio: bool,
    ) -> None:
        """Interpret a presentation Live request and start it outside the GUI thread."""

        def operation() -> None:
            settings = self.controller.settings
            source = (
                audio_source
                if audio_source in AudioSource.choices()
                else settings.audio_source
            )
            selection = str(selected_input or "").strip()
            resolved_language = str(language or "").strip() or settings.language
            sink_name: str | None = None
            stream_id: int | None = None

            if source == AudioSource.APPLICATION.value:
                if not selection:
                    raise ValueError(
                        "Seleziona uno stream applicazione prima di avviare la sessione"
                    )
                try:
                    stream_id = int(selection)
                except ValueError as exc:
                    raise ValueError(
                        "Identificatore dello stream applicazione non valido"
                    ) from exc
            else:
                sink_name = selection or None

            if self.meeting.is_busy():
                raise RuntimeError(
                    "Termina la riunione prima di avviare una sessione Live"
                )
            if self.controller.is_file_busy():
                raise RuntimeError("Ferma la trascrizione File prima di avviare Live")
            self.controller.start_live_session(
                sink_name=sink_name,
                audio_source=source,
                language=resolved_language,
                stream_id=stream_id,
                record_audio=bool(
                    record_audio and source == AudioSource.MICROPHONE.value
                ),
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
        settings = self.controller.settings
        resolved_language = str(language or "").strip() or settings.language
        resolved_model = (
            model_size if model_size in ModelSize.choices() else settings.model_size
        )
        source = Path(path).expanduser()
        if not source.is_file():
            raise FileNotFoundError("Seleziona un file esistente")
        if self.meeting.is_busy():
            raise RuntimeError(
                "Termina la riunione prima di avviare una trascrizione File"
            )
        self.controller.start_file_transcription(
            str(source),
            language=resolved_language,
            model_size=resolved_model,
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
        settings = self.controller.settings
        resolved_language = str(language or "").strip() or settings.language
        resolved_model = (
            model_size if model_size in ModelSize.choices() else settings.model_size
        )
        if self.meeting.is_busy():
            raise RuntimeError("Termina la riunione prima di accodare file")
        return self.file_batch.enqueue(
            paths,
            language=resolved_language,
            model_size=resolved_model,
            song_mode=song_mode,
            isolate_vocals=isolate_vocals,
        )

    def existing_files(self, paths: list[str]) -> list[str]:
        return [
            str(path)
            for raw in paths
            if (path := Path(str(raw)).expanduser()).is_file()
        ]

    def list_file_queue(self) -> list[dict[str, Any]]:
        return self.file_batch.list_jobs()

    def cancel_file_queue(self) -> list[dict[str, Any]]:
        return self.file_batch.cancel(clear_pending=True)

    def clear_finished_file_queue(self) -> list[dict[str, Any]]:
        return self.file_batch.clear_finished()

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

    def finish_meeting(self) -> dict[str, Any]:
        return self.meeting.finish()

    def cancel_meeting(self) -> dict[str, Any] | None:
        self.meeting.cancel()
        return self.meeting.snapshot()

    def get_meeting(self, session_id: str) -> dict[str, Any] | None:
        return self.meeting.get(session_id)

    def meeting_audio_path(self, session_id: str) -> str:
        meeting = self.meeting.get(session_id)
        path = Path(
            str((meeting or {}).get("meeting", {}).get("recording", {}).get("path") or "")
        )
        return str(path) if path.is_file() else ""

    def set_meeting_speaker_name(
        self, session_id: str, speaker_id: str, name: str
    ) -> dict[str, Any]:
        return self.meeting.set_speaker_name(session_id, speaker_id, name)

    def edit_meeting_segment(
        self, session_id: str, index: int, text: str
    ) -> dict[str, Any]:
        return self.meeting.edit_segment(session_id, index, text)

    def delete_meeting_audio(self, session_id: str) -> bool:
        return self.meeting.delete_audio(session_id)

    def require_meeting_idle(self, action: str) -> None:
        if self.meeting.is_busy():
            raise RuntimeError(f"Termina la riunione prima di {action}")

    def _require_transcription_idle(self) -> None:
        if self.controller.active_live_count() > 0 or self.controller.is_file_busy():
            raise RuntimeError(
                "Ferma la trascrizione attiva prima di gestire i modelli"
            )

    def list_models(self) -> list[dict[str, object]]:
        return self.controller.list_models()

    def download_model(self, model_size: str) -> None:
        self.require_meeting_idle("gestire i modelli")
        self._require_transcription_idle()
        self.submit(
            f"download-model-{model_size}",
            lambda: self.controller.download_model(model_size),
            "model_download_error",
        )

    def delete_model(self, model_size: str) -> None:
        self.require_meeting_idle("gestire i modelli")
        self._require_transcription_idle()
        self.submit(
            f"delete-model-{model_size}",
            lambda: self.controller.delete_model(model_size),
            "model_delete_error",
        )

    def list_history(self, limit: int) -> list[dict[str, Any]]:
        return self.controller.list_history(limit)

    def search_history(self, query: str, limit: int) -> list[dict[str, Any]]:
        self.controller.prune_history()
        return self.controller.history.search(query, limit)

    def get_history_session(self, session_id: str) -> dict[str, Any] | None:
        session = self.controller.get_history_session(session_id)
        if session and session.get("kind") == "meeting":
            meeting = self.meeting.get(session_id)
            if meeting is not None:
                meeting["name"] = str(session.get("name") or "")
                session = meeting
        return session

    def rename_history_session(self, session_id: str, name: str) -> str:
        cleaned = self.controller.history.set_name(session_id, name)
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

    def list_recovery_audio(self) -> list[dict[str, Any]]:
        return self.controller.list_recovery_audio()

    def start_recovery(self, recovery_path: str) -> None:
        self.require_meeting_idle("recuperare audio")
        self.controller.start_recovery_transcription(recovery_path)

    def delete_recovery(self, recovery_path: str) -> bool:
        return self.controller.delete_recovery_audio(recovery_path)

    def read_log_tail(self, line_count: int) -> str:
        try:
            with AppMeta.LOG_PATH.open(
                "r", encoding="utf-8", errors="replace"
            ) as handle:
                lines = handle.readlines()
            return "".join(lines[-line_count:])
        except OSError as exc:
            logger.debug("Log applicativo non disponibile: %s", exc)
            return ""

    def run_audio_diagnostics(self) -> None:
        self.submit(
            "audio-diagnostics",
            lambda: self._bus.emit(
                "audio_diagnostics",
                build_audio_diagnostics(self.controller),
            ),
            "audio_diagnostics_error",
        )