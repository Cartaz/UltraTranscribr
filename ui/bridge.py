"""Qt WebChannel bridge between the HTML frontend and Python backend."""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from config.constants import AppMeta
from config.settings import AudioSource, ModelSize
from core.app_controller import AppController
from core.sink_finder import debug_dump

logger = logging.getLogger(__name__)


class BackendBridge(QObject):
    """Expose a deliberately small, presentation-oriented API to JavaScript."""

    eventReceived = Signal(str, str)
    logReceived = Signal(str, str, str)
    windowResizeRequested = Signal(int, int)

    _EVENTS = (
        "backend_status_changed",
        "process_started",
        "process_stopped",
        "capture_stopped",
        "transcriber_status_changed",
        "transcriber_buffer_level",
        "transcriber_new_text",
        "transcriber_error",
        "transcriber_drained",
        "file_transcriber_status_changed",
        "file_transcriber_progress",
        "file_transcriber_new_text",
        "file_transcriber_full_text",
        "file_transcriber_completed",
        "file_transcriber_error",
        "config_changed",
        "history_changed",
        "history_error",
        "recovery_audio_saved",
        "model_download_started",
        "model_download_progress",
        "model_status_changed",
        "playback_stream_status_changed",
        "audio_devices_changed",
        "playback_streams_changed",
        "audio_source_health_changed",
        "audio_discovery_error",
    )

    def __init__(self, controller: AppController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._subscriptions: list[tuple[str, Callable[[Any], None]]] = []
        self._backend_reload_required = False
        self._backend_reload_lock = threading.Lock()
        for event in self._EVENTS:
            handler = self._make_event_handler(event)
            self._controller.subscribe(event, handler)
            self._subscriptions.append((event, handler))

    def _make_event_handler(self, event: str) -> Callable[[Any], None]:
        def handler(payload: Any) -> None:
            self._emit_event(event, payload)

        handler.__name__ = f"web_bridge_{event}"
        return handler

    def _emit_event(self, event: str, payload: Any = None) -> None:
        try:
            encoded = json.dumps(payload, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            encoded = json.dumps(str(payload), ensure_ascii=False)
        self.eventReceived.emit(event, encoded)

    def _run_async(
        self,
        name: str,
        operation: Callable[[], None],
        error_event: str,
    ) -> None:
        def worker() -> None:
            try:
                operation()
            except Exception as exc:
                logger.exception("Operazione UI '%s' fallita", name)
                self._emit_event(error_event, str(exc))

        threading.Thread(
            target=worker,
            daemon=True,
            name=f"UIBridge-{name}",
        ).start()

    @Slot(result=str)
    def getBootstrap(self) -> str:
        settings = asdict(self._controller.settings)
        discovery = self._controller.audio_discovery_snapshot()
        self._controller.request_audio_discovery()
        payload = {
            "app": {
                "name": AppMeta.NAME,
                "version": AppMeta.VERSION,
                "description": AppMeta.DESCRIPTION,
            },
            "settings": settings,
            "modelChoices": ModelSize.choices(),
            "models": self._controller.list_models(),
            "audioSources": AudioSource.choices(),
            "devices": discovery["devices"],
            "playbackStreams": discovery["streams"],
            "runtime": {
                "liveRunning": self._controller.is_running(),
                "liveDraining": self._controller.is_draining(),
                "fileRunning": self._controller.is_file_transcribing(),
                "backendRunning": self._controller.backend.is_running,
                "bufferLevel": self._controller.buffer.buffer_level,
            },
            "logTail": self._read_log_tail(160),
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

    @Slot(str, result=str)
    def refreshDevices(self, audio_source: str) -> str:
        source = (
            audio_source
            if audio_source in AudioSource.choices()
            else self._controller.settings.audio_source
        )
        if source == AudioSource.APPLICATION.value:
            return "[]"
        self._controller.request_audio_discovery(devices=True, streams=False)
        devices = self._controller.audio_discovery_snapshot()["devices"]
        key = "is_monitor" if source == AudioSource.SYSTEM.value else "is_mic"
        filtered = [device for device in devices if bool(device.get(key))]
        return json.dumps(filtered, ensure_ascii=False, default=str)

    @Slot(result=str)
    def listPlaybackStreams(self) -> str:
        self._controller.request_audio_discovery(devices=False, streams=True)
        streams = self._controller.audio_discovery_snapshot()["streams"]
        return json.dumps(streams, ensure_ascii=False, default=str)

    def _prepare_backend_for_selected_model(self) -> None:
        with self._backend_reload_lock:
            reload_required = self._backend_reload_required
            self._backend_reload_required = False
        if reload_required and self._controller.backend.is_running:
            self._controller.stop_backend()

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
                    "transcriber_error",
                    "Seleziona uno stream applicazione prima di avviare la trascrizione",
                )
                return
            try:
                stream_id = int(selection)
            except ValueError:
                self._emit_event(
                    "transcriber_error",
                    "Identificatore dello stream applicazione non valido",
                )
                return
        else:
            sink = selection or None

        def operation() -> None:
            self._prepare_backend_for_selected_model()
            self._controller.start_transcription(
                sink_name=sink,
                audio_source=source,
                language=lang,
                stream_id=stream_id,
            )

        self._run_async("start-live", operation, "transcriber_error")

    @Slot()
    def stopLive(self) -> None:
        self._run_async(
            "stop-live",
            self._controller.stop_transcription,
            "transcriber_error",
        )

    @Slot()
    def stopListening(self) -> None:
        self._run_async(
            "stop-listening",
            self._controller.stop_listening,
            "transcriber_error",
        )

    @Slot(result=str)
    def chooseAudioFile(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            None,
            "Seleziona file audio o video",
            "",
            "Media (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.opus *.mp4 *.mkv *.webm *.mov *.avi);;Tutti i file (*)",
        )
        return path

    @Slot(str, str, str, bool, bool)
    def startFile(
        self,
        file_path: str,
        language: str,
        model_size: str,
        song_mode: bool,
        isolate_vocals: bool,
    ) -> None:
        path = Path(file_path).expanduser()
        if not path.is_file():
            self._emit_event(
                "file_transcriber_error",
                "Seleziona un file esistente",
            )
            return
        lang = language.strip() or self._controller.settings.language
        model = (
            model_size
            if model_size in ModelSize.choices()
            else self._controller.settings.model_size
        )

        def operation() -> None:
            self._prepare_backend_for_selected_model()
            self._controller.start_file_transcription(
                str(path),
                language=lang,
                model_size=model,
                song_mode=bool(song_mode),
                isolate_vocals_flag=bool(isolate_vocals and song_mode),
            )

        self._run_async("start-file", operation, "file_transcriber_error")

    @Slot()
    def stopFile(self) -> None:
        self._run_async(
            "stop-file",
            self._controller.stop_file_transcription,
            "file_transcriber_error",
        )

    @Slot(result=str)
    def listModels(self) -> str:
        return json.dumps(
            self._controller.list_models(),
            ensure_ascii=False,
            default=str,
        )

    @Slot(str, result=str)
    def downloadModel(self, model_size: str) -> str:
        if (
            self._controller.is_running()
            or self._controller.is_draining()
            or self._controller.is_file_transcribing()
        ):
            return json.dumps(
                {
                    "ok": False,
                    "error": "Ferma la trascrizione attiva prima di scaricare un modello",
                },
                ensure_ascii=False,
            )
        self._run_async(
            f"download-model-{model_size}",
            lambda: self._controller.download_model(model_size),
            "model_download_error",
        )
        return json.dumps({"ok": True}, ensure_ascii=False)

    @Slot(str, result=str)
    def deleteModel(self, model_size: str) -> str:
        if (
            self._controller.is_running()
            or self._controller.is_draining()
            or self._controller.is_file_transcribing()
        ):
            return json.dumps(
                {
                    "ok": False,
                    "error": "Ferma la trascrizione attiva prima di eliminare un modello",
                },
                ensure_ascii=False,
            )
        self._run_async(
            f"delete-model-{model_size}",
            lambda: self._controller.delete_model(model_size),
            "model_delete_error",
        )
        return json.dumps({"ok": True}, ensure_ascii=False)

    @Slot(int, result=str)
    def listHistory(self, limit: int = 50) -> str:
        return json.dumps(
            self._controller.list_history(max(1, min(int(limit), 500))),
            ensure_ascii=False,
            default=str,
        )

    @Slot(str, result=str)
    def getHistorySession(self, session_id: str) -> str:
        session = self._controller.get_history_session(session_id)
        return json.dumps(session, ensure_ascii=False, default=str)

    @Slot(str, result=str)
    def exportHistorySession(self, session_id: str) -> str:
        try:
            session = self._controller.get_history_session(session_id)
            if not session:
                raise KeyError("sessione non trovata")
            source_path = str(session.get("source_path") or "")
            stem = Path(source_path).stem if source_path else session_id
            default_path = str(Path.home() / f"{stem or session_id}.txt")
            target, _ = QFileDialog.getSaveFileName(
                None,
                "Esporta trascrizione",
                default_path,
                "Testo (*.txt)",
            )
            if not target:
                return json.dumps(
                    {"ok": False, "cancelled": True},
                    ensure_ascii=False,
                )
            exported = self._controller.export_history_session(
                session_id,
                target,
            )
            return json.dumps(
                {"ok": True, "path": exported},
                ensure_ascii=False,
            )
        except Exception as exc:
            logger.warning("Export cronologia fallito: %s", exc)
            return json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
            )

    @Slot(str, result=str)
    def deleteHistorySession(self, session_id: str) -> str:
        try:
            deleted = self._controller.delete_history_session(session_id)
            return json.dumps(
                {"ok": True, "deleted": deleted},
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
            )

    @Slot(result=str)
    def listRecoveryAudio(self) -> str:
        return json.dumps(
            self._controller.list_recovery_audio(),
            ensure_ascii=False,
            default=str,
        )

    @Slot(str, result=str)
    def startRecovery(self, recovery_path: str) -> str:
        try:
            self._prepare_backend_for_selected_model()
            self._controller.start_recovery_transcription(recovery_path)
            return json.dumps({"ok": True}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
            )

    @Slot(str, result=str)
    def deleteRecovery(self, recovery_path: str) -> str:
        try:
            deleted = self._controller.delete_recovery_audio(recovery_path)
            return json.dumps(
                {"ok": True, "deleted": deleted},
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
            )

    @Slot(str, result=str)
    def applySettings(self, payload_json: str) -> str:
        try:
            payload = json.loads(payload_json)
            if not isinstance(payload, dict):
                raise ValueError("payload impostazioni non valido")
            allowed = set(self._controller.settings.__dataclass_fields__)
            overrides = {
                key: value
                for key, value in payload.items()
                if key in allowed
            }
            current_before = self._controller.settings
            old_width = current_before.window_width
            old_height = current_before.window_height

            model_changed = (
                "model_size" in overrides
                and overrides["model_size"] != current_before.model_size
            )
            if model_changed and (
                self._controller.is_running()
                or self._controller.is_draining()
                or self._controller.is_file_transcribing()
            ):
                raise RuntimeError(
                    "Ferma la trascrizione attiva prima di cambiare modello"
                )
            if model_changed and self._controller.backend.is_running:
                with self._backend_reload_lock:
                    self._backend_reload_required = True

            self._controller.update_settings(**overrides)
            current = self._controller.settings
            if (
                current.window_width != old_width
                or current.window_height != old_height
            ):
                self.windowResizeRequested.emit(
                    current.window_width,
                    current.window_height,
                )
            return json.dumps(
                {"ok": True, "settings": asdict(current)},
                ensure_ascii=False,
            )
        except Exception as exc:
            logger.warning("Impostazioni rifiutate: %s", exc)
            return json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
            )

    @Slot(int, result=str)
    def readLogTail(self, line_count: int = 200) -> str:
        return self._read_log_tail(max(20, min(int(line_count), 1000)))

    @Slot()
    def runAudioDiagnostics(self) -> None:
        def operation() -> None:
            report = debug_dump()
            try:
                streams = self._controller.list_playback_streams()
            except Exception as exc:
                streams = []
                report += f"\n\n=== playback streams ===\n  Errore: {exc}"
            else:
                report += "\n\n=== playback streams ==="
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
            self._emit_event("audio_diagnostics", report)

        self._run_async(
            "audio-diagnostics",
            operation,
            "audio_diagnostics_error",
        )

    def push_log_record(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        self.logReceived.emit(record.levelname, record.name, message)

    @staticmethod
    def _read_log_tail(line_count: int) -> str:
        try:
            with AppMeta.LOG_PATH.open(
                "r",
                encoding="utf-8",
                errors="replace",
            ) as handle:
                lines = handle.readlines()
            return "".join(lines[-line_count:])
        except OSError:
            return ""


class BridgeLogHandler(logging.Handler):
    """Mirror Python log records into the embedded frontend."""

    def __init__(self, bridge: BackendBridge) -> None:
        super().__init__(level=logging.INFO)
        self._bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        self._bridge.push_log_record(record)
