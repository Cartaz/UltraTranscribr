"""Single Qt WebChannel boundary between the local web UI and Python application."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from config.constants import AppMeta
from config.settings import AudioSource, ModelSize
from core.application_service import ApplicationService

logger = logging.getLogger(__name__)


class BackendBridge(QObject):
    """Validate/serialize WebChannel values and delegate application behavior."""

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
        "file_transcriber_segments",
        "file_queue_changed",
        "file_queue_job_updated",
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
        "audio_diagnostics",
        "audio_diagnostics_error",
        "backend_preload_error",
        "live_session_created",
        "live_session_updated",
        "live_session_buffer_level",
        "live_session_queue_wait",
        "live_session_text",
        "live_session_error",
        "live_session_start_error",
        "live_session_action_error",
        "live_session_route_status",
        "live_session_removed",
        "microphone_recording_saved",
        "meeting_started",
        "meeting_updated",
        "meeting_recording_saved",
        "meeting_model_progress",
        "meeting_completed",
        "meeting_error",
        "meeting_review_changed",
    )

    _MEDIA_FILTER = (
        "Media (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.opus *.mp4 *.mkv "
        "*.webm *.mov *.avi);;Tutti i file (*)"
    )
    _EXPORT_FILTERS = {
        "txt": "Testo (*.txt)",
        "srt": "SubRip (*.srt)",
        "vtt": "WebVTT (*.vtt)",
    }

    def __init__(
        self,
        application: ApplicationService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._application = application
        for event in self._EVENTS:
            handler = self._make_event_handler(event)
            self._application.subscribe(event, handler)
        QTimer.singleShot(0, self._application.preload_model_if_requested)

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

    @staticmethod
    def _ok(**payload: Any) -> str:
        return json.dumps({"ok": True, **payload}, ensure_ascii=False, default=str)

    @staticmethod
    def _error(exc: Exception | str) -> str:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(result=str)
    def getBootstrap(self) -> str:
        payload = self._application.bootstrap_snapshot()
        payload["app"] = {
            "name": AppMeta.NAME,
            "version": AppMeta.VERSION,
            "description": AppMeta.DESCRIPTION,
        }
        payload["logTail"] = self._application.read_log_tail(160)
        return json.dumps(payload, ensure_ascii=False, default=str)

    @Slot(result=str)
    def getSettingsDefaults(self) -> str:
        return json.dumps(
            self._application.settings_defaults(), ensure_ascii=False, default=str
        )

    @Slot(str, result=str)
    def refreshDevices(self, audio_source: str) -> str:
        return json.dumps(
            self._application.refresh_devices(audio_source),
            ensure_ascii=False,
            default=str,
        )

    @Slot(result=str)
    def listPlaybackStreams(self) -> str:
        return json.dumps(
            self._application.list_playback_streams(),
            ensure_ascii=False,
            default=str,
        )

    @Slot(str, str, result=str)
    def probeAudioSource(self, audio_source: str, selected_input: str) -> str:
        return json.dumps(
            self._application.probe_audio_source(audio_source, selected_input),
            ensure_ascii=False,
            default=str,
        )

    def _start_live(
        self,
        audio_source: str,
        selected_input: str,
        language: str,
        record_audio: bool,
    ) -> None:
        settings = self._application.settings
        source = (
            audio_source
            if audio_source in AudioSource.choices()
            else settings.audio_source
        )
        selection = str(selected_input or "").strip()
        language = str(language or "").strip() or settings.language
        sink_name: str | None = None
        stream_id: int | None = None
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
            sink_name = selection or None
        self._application.start_live(
            sink_name=sink_name,
            audio_source=source,
            language=language,
            stream_id=stream_id,
            record_audio=bool(
                record_audio and source == AudioSource.MICROPHONE.value
            ),
        )

    @Slot(str, str, str)
    def startLive(self, audio_source: str, selected_input: str, language: str) -> None:
        self._start_live(audio_source, selected_input, language, False)

    @Slot(str, str, str, bool)
    def startLiveWithRecording(
        self,
        audio_source: str,
        selected_input: str,
        language: str,
        record_audio: bool,
    ) -> None:
        self._start_live(audio_source, selected_input, language, record_audio)

    @Slot(str)
    def stopLiveSession(self, session_id: str) -> None:
        self._application.stop_live(session_id, drain=False)

    @Slot(str)
    def drainLiveSession(self, session_id: str) -> None:
        self._application.stop_live(session_id, drain=True)

    @Slot(str)
    def removeLiveSession(self, session_id: str) -> None:
        self._application.remove_live(session_id)

    @Slot()
    def stopAllLive(self) -> None:
        self._application.stop_all_live(drain=False)

    @Slot()
    def drainAllLive(self) -> None:
        self._application.stop_all_live(drain=True)

    @Slot()
    def stopLive(self) -> None:
        self.stopAllLive()

    @Slot()
    def stopListening(self) -> None:
        self.drainAllLive()

    @Slot(str, str, int, result=str)
    def startMeeting(self, microphone: str, language: str, num_speakers: int) -> str:
        try:
            meeting = self._application.start_meeting(
                microphone=microphone.strip() or None,
                language=language.strip() or None,
                num_speakers=max(0, int(num_speakers)),
            )
            return self._ok(meeting=meeting)
        except Exception as exc:
            return self._error(exc)

    @Slot(result=str)
    def finishMeeting(self) -> str:
        try:
            return self._ok(meeting=self._application.finish_meeting())
        except Exception as exc:
            return self._error(exc)

    @Slot(result=str)
    def cancelMeeting(self) -> str:
        try:
            return self._ok(meeting=self._application.cancel_meeting())
        except Exception as exc:
            return self._error(exc)

    @Slot(str, result=str)
    def getMeetingSession(self, session_id: str) -> str:
        return json.dumps(
            self._application.get_meeting(session_id),
            ensure_ascii=False,
            default=str,
        )

    @Slot(str, result=str)
    def getMeetingAudioUrl(self, session_id: str) -> str:
        path = self._application.meeting_audio_path(session_id)
        return QUrl.fromLocalFile(path).toString() if path else ""

    @Slot(str, str, str, result=str)
    def setMeetingSpeakerName(self, session_id: str, speaker_id: str, name: str) -> str:
        try:
            meeting = self._application.set_meeting_speaker_name(
                session_id, speaker_id, name
            )
            return self._ok(meeting=meeting)
        except Exception as exc:
            return self._error(exc)

    @Slot(str, int, str, result=str)
    def editMeetingSegment(self, session_id: str, index: int, text: str) -> str:
        try:
            meeting = self._application.edit_meeting_segment(
                session_id, index, text
            )
            return self._ok(meeting=meeting)
        except Exception as exc:
            return self._error(exc)

    @Slot(str, result=str)
    def deleteMeetingAudio(self, session_id: str) -> str:
        try:
            return self._ok(
                deleted=self._application.delete_meeting_audio(session_id)
            )
        except Exception as exc:
            return self._error(exc)

    @Slot(str, str, result=str)
    def exportMeetingFormat(self, session_id: str, format_name: str) -> str:
        return self.exportHistoryFormat(session_id, format_name, "raw")

    @Slot(result=str)
    def chooseAudioFile(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            None, "Seleziona file audio o video", "", self._MEDIA_FILTER
        )
        return path

    @Slot(result=str)
    def chooseAudioFiles(self) -> str:
        paths, _ = QFileDialog.getOpenFileNames(
            None, "Seleziona file audio o video", "", self._MEDIA_FILTER
        )
        return json.dumps(paths, ensure_ascii=False)

    @Slot(str, str, str, bool, bool)
    def startFile(
        self,
        file_path: str,
        language: str,
        model_size: str,
        song_mode: bool,
        isolate_vocals: bool,
    ) -> None:
        settings = self._application.settings
        language = language.strip() or settings.language
        model_size = (
            model_size
            if model_size in ModelSize.choices()
            else settings.model_size
        )
        try:
            self._application.start_file(
                file_path,
                language=language,
                model_size=model_size,
                song_mode=bool(song_mode),
                isolate_vocals=bool(isolate_vocals),
            )
        except Exception as exc:
            self._emit_event("file_transcriber_error", str(exc))

    @Slot()
    def stopFile(self) -> None:
        self._application.stop_file()

    @Slot(str, str, str, bool, bool, result=str)
    def enqueueFileBatch(
        self,
        paths_json: str,
        language: str,
        model_size: str,
        song_mode: bool,
        isolate_vocals: bool,
    ) -> str:
        try:
            decoded = json.loads(paths_json)
            if not isinstance(decoded, list):
                raise ValueError("elenco file non valido")
            paths = [str(path) for path in decoded if str(path).strip()]
            settings = self._application.settings
            jobs = self._application.enqueue_files(
                paths,
                language=language.strip() or settings.language,
                model_size=model_size.strip() or settings.model_size,
                song_mode=bool(song_mode),
                isolate_vocals=bool(isolate_vocals),
            )
            return self._ok(jobs=jobs)
        except Exception as exc:
            return self._error(exc)

    @Slot(result=str)
    def listFileQueue(self) -> str:
        return json.dumps(
            self._application.list_file_queue(), ensure_ascii=False, default=str
        )

    @Slot(result=str)
    def cancelFileQueue(self) -> str:
        return self._ok(jobs=self._application.cancel_file_queue())

    @Slot(result=str)
    def clearFinishedFileQueue(self) -> str:
        return self._ok(jobs=self._application.clear_finished_file_queue())

    def emitDroppedFiles(self, paths: list[str]) -> None:
        existing = self._application.existing_files(paths)
        if existing:
            self._emit_event("file_drop_received", existing)

    @Slot(result=str)
    def listModels(self) -> str:
        return json.dumps(
            self._application.list_models(), ensure_ascii=False, default=str
        )

    @Slot(str, result=str)
    def downloadModel(self, model_size: str) -> str:
        try:
            self._application.download_model(model_size)
            return self._ok()
        except Exception as exc:
            return self._error(exc)

    @Slot(str, result=str)
    def deleteModel(self, model_size: str) -> str:
        try:
            self._application.delete_model(model_size)
            return self._ok()
        except Exception as exc:
            return self._error(exc)

    @Slot(int, result=str)
    def listHistory(self, limit: int = 50) -> str:
        return json.dumps(
            self._application.list_history(max(1, min(int(limit), 500))),
            ensure_ascii=False,
            default=str,
        )

    @Slot(str, int, result=str)
    def searchHistory(self, query: str, limit: int = 100) -> str:
        return json.dumps(
            self._application.search_history(
                query, max(1, min(int(limit), 500))
            ),
            ensure_ascii=False,
            default=str,
        )

    @Slot(str, result=str)
    def getHistorySession(self, session_id: str) -> str:
        return json.dumps(
            self._application.get_history_session(session_id),
            ensure_ascii=False,
            default=str,
        )

    @Slot(str, str, result=str)
    def generatePostprocess(self, session_id: str, profile: str) -> str:
        try:
            return self._ok(
                **self._application.generate_postprocess(session_id, profile)
            )
        except Exception as exc:
            return self._error(exc)

    @Slot(str, str, result=str)
    def renameHistorySession(self, session_id: str, name: str) -> str:
        try:
            return self._ok(
                name=self._application.rename_history_session(session_id, name)
            )
        except Exception as exc:
            return self._error(exc)

    @Slot(str, result=str)
    def exportHistorySession(self, session_id: str) -> str:
        return self.exportHistoryFormat(session_id, "txt", "raw")

    @Slot(str, str, str, result=str)
    def exportHistoryFormat(
        self,
        session_id: str,
        format_name: str,
        profile: str = "raw",
    ) -> str:
        try:
            session = self._application.get_history_session(session_id)
            if not session:
                raise KeyError("sessione non trovata")
            fmt = str(format_name or "txt").strip().lower().lstrip(".")
            if fmt not in self._EXPORT_FILTERS:
                raise ValueError("formato export non supportato")
            source_path = str(session.get("source_path") or "")
            stem = "meeting-" + session_id if session.get("kind") == "meeting" else (
                Path(source_path).stem if source_path else session_id
            )
            target, _ = QFileDialog.getSaveFileName(
                None,
                "Esporta riunione" if session.get("kind") == "meeting" else "Esporta trascrizione",
                str(Path.home() / f"{stem}.{fmt}"),
                self._EXPORT_FILTERS[fmt],
            )
            if not target:
                return json.dumps({"ok": False, "cancelled": True}, ensure_ascii=False)
            return self._ok(
                path=self._application.export_history_format(
                    session_id, target, fmt, profile or "raw"
                )
            )
        except Exception as exc:
            logger.warning("Export cronologia %s fallito: %s", format_name, exc)
            return self._error(exc)

    @Slot(str, result=str)
    def deleteHistorySession(self, session_id: str) -> str:
        try:
            return self._ok(
                deleted=self._application.delete_history_session(session_id)
            )
        except Exception as exc:
            return self._error(exc)

    @Slot(str, result=str)
    def getSessionRecordingInfo(self, session_id: str) -> str:
        try:
            info = self._application.session_recording_info(session_id)
            if info.get("exists"):
                info["url"] = QUrl.fromLocalFile(str(info["path"])).toString()
            return json.dumps(info, ensure_ascii=False, default=str)
        except Exception as exc:
            return json.dumps(
                {"exists": False, "error": str(exc)}, ensure_ascii=False
            )

    @Slot(str, result=str)
    def deleteSessionRecording(self, session_id: str) -> str:
        try:
            return self._ok(
                deleted=self._application.delete_session_recording(session_id)
            )
        except Exception as exc:
            return self._error(exc)

    @Slot(result=str)
    def listRecoveryAudio(self) -> str:
        return json.dumps(
            self._application.list_recovery_audio(), ensure_ascii=False, default=str
        )

    @Slot(str, result=str)
    def startRecovery(self, recovery_path: str) -> str:
        try:
            self._application.start_recovery(recovery_path)
            return self._ok()
        except Exception as exc:
            return self._error(exc)

    @Slot(str, result=str)
    def deleteRecovery(self, recovery_path: str) -> str:
        try:
            return self._ok(deleted=self._application.delete_recovery(recovery_path))
        except Exception as exc:
            return self._error(exc)

    @Slot(str, result=str)
    def applySettings(self, payload_json: str) -> str:
        try:
            payload = json.loads(payload_json)
            if not isinstance(payload, dict):
                raise ValueError("payload impostazioni non valido")
            overrides = self._application.filter_settings_overrides(payload)
            before = self._application.settings
            current = self._application.apply_settings(overrides)
            if (
                current.window_width != before.window_width
                or current.window_height != before.window_height
            ):
                self.windowResizeRequested.emit(
                    current.window_width, current.window_height
                )
            return self._ok(settings=asdict(current))
        except Exception as exc:
            logger.warning("Impostazioni rifiutate: %s", exc)
            return self._error(exc)

    @Slot()
    def runAudioDiagnostics(self) -> None:
        self._application.run_audio_diagnostics()

    @Slot(int, result=str)
    def readLogTail(self, line_count: int = 200) -> str:
        return self._application.read_log_tail(
            max(20, min(int(line_count), 1000))
        )

    def push_log_record(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        self.logReceived.emit(record.levelname, record.name, message)


class BridgeLogHandler(logging.Handler):
    """Mirror Python log records into the embedded frontend."""

    def __init__(self, bridge: BackendBridge) -> None:
        super().__init__(level=logging.INFO)
        self._bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        self._bridge.push_log_record(record)
