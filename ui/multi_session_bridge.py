"""Multi-session WebChannel API layered on the existing presentation bridge."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QUrl, Slot
from PySide6.QtWidgets import QFileDialog

from config.settings import AudioSource, Settings
from core.audio_diagnostics import build_audio_diagnostics
from core.transcript_postprocess import process_text, profile_choices
from ui.bridge import BackendBridge

logger = logging.getLogger(__name__)


class MultiSessionBackendBridge(BackendBridge):
    """Expose Live, File power-user and Meeting workflows."""

    _EVENTS = BackendBridge._EVENTS + (
        "live_session_created",
        "live_session_updated",
        "live_session_buffer_level",
        "live_session_queue_wait",
        "live_session_text",
        "live_session_error",
        "live_session_route_status",
        "live_session_removed",
        "file_transcriber_segments",
        "file_queue_changed",
        "file_queue_job_updated",
        "microphone_recording_saved",
        "meeting_started",
        "meeting_updated",
        "meeting_recording_saved",
        "meeting_model_progress",
        "meeting_completed",
        "meeting_error",
        "meeting_review_changed",
    )

    def __init__(self, controller, parent=None) -> None:
        super().__init__(controller, parent)
        self._file_batch = controller.file_batch
        self._meeting = controller.meeting

    @Slot(result=str)
    def getBootstrap(self) -> str:
        payload = json.loads(super().getBootstrap())
        sessions = self._controller.list_live_sessions(include_text=True)
        payload["liveSessions"] = sessions
        payload["fileQueue"] = self._file_batch.list_jobs()
        payload["postprocessProfiles"] = profile_choices()
        payload["meetingRuntime"] = self._meeting.snapshot()
        payload["diarizationModels"] = self._meeting.models.status()
        runtime = payload.setdefault("runtime", {})
        runtime["liveSessionCount"] = sum(
            1 for session in sessions if not bool(session.get("terminal"))
        )
        runtime["liveRunning"] = self._controller.is_running()
        runtime["liveDraining"] = self._controller.is_draining()
        runtime["bufferLevel"] = self._controller.buffer.buffer_level
        runtime["meetingBusy"] = self._meeting.is_busy()
        return json.dumps(payload, ensure_ascii=False, default=str)

    @Slot(result=str)
    def getSettingsDefaults(self) -> str:
        return json.dumps(asdict(Settings()), ensure_ascii=False, default=str)

    @Slot(result=str)
    def listLiveSessions(self) -> str:
        return json.dumps(
            self._controller.list_live_sessions(include_text=True),
            ensure_ascii=False,
            default=str,
        )

    @Slot(str, str, result=str)
    def probeAudioSource(self, audio_source: str, selected_input: str) -> str:
        source = (
            audio_source
            if audio_source in AudioSource.choices()
            else self._controller.settings.audio_source
        )
        selection = str(selected_input or "").strip()
        status = self._controller.cached_audio_source_health(source, selection)
        self._controller.request_audio_source_probe(source, selection)
        return json.dumps(status, ensure_ascii=False, default=str)

    def _start_live_impl(
        self,
        audio_source: str,
        selected_input: str,
        language: str,
        record_audio: bool,
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
        save_recording = bool(record_audio and source == AudioSource.MICROPHONE.value)

        def operation() -> None:
            if self._meeting.is_busy():
                raise RuntimeError("Termina la riunione prima di avviare una sessione Live")
            self._prepare_backend_for_selected_model()
            self._controller.start_live_session(
                sink_name=sink,
                audio_source=source,
                language=lang,
                stream_id=stream_id,
                record_audio=save_recording,
            )

        self._run_async(
            "start-live-session",
            operation,
            "live_session_start_error",
        )

    @Slot(str, str, str)
    def startLive(self, audio_source: str, selected_input: str, language: str) -> None:
        self._start_live_impl(audio_source, selected_input, language, False)

    @Slot(str, str, str, bool)
    def startLiveWithRecording(
        self,
        audio_source: str,
        selected_input: str,
        language: str,
        record_audio: bool,
    ) -> None:
        self._start_live_impl(audio_source, selected_input, language, record_audio)

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

    # ------------------------------------------------------------------
    # Meeting workflow
    # ------------------------------------------------------------------
    @Slot(str, str, int, result=str)
    def startMeeting(self, microphone: str, language: str, num_speakers: int) -> str:
        try:
            runtime = self._meeting.start(
                microphone=microphone.strip() or None,
                language=language.strip() or None,
                num_speakers=max(0, int(num_speakers)),
            )
            return json.dumps({"ok": True, "meeting": runtime}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(result=str)
    def finishMeeting(self) -> str:
        try:
            runtime = self._meeting.finish()
            return json.dumps({"ok": True, "meeting": runtime}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(result=str)
    def cancelMeeting(self) -> str:
        self._meeting.cancel()
        return json.dumps({"ok": True, "meeting": self._meeting.snapshot()}, ensure_ascii=False)

    @Slot(str, result=str)
    def getMeetingSession(self, session_id: str) -> str:
        return json.dumps(self._meeting.get(session_id), ensure_ascii=False, default=str)

    @Slot(str, result=str)
    def getMeetingAudioUrl(self, session_id: str) -> str:
        meeting = self._meeting.get(session_id)
        if not meeting:
            return ""
        path = str((meeting.get("meeting") or {}).get("recording", {}).get("path") or "")
        if not path or not Path(path).is_file():
            return ""
        return QUrl.fromLocalFile(path).toString()

    @Slot(str, str, str, result=str)
    def setMeetingSpeakerName(self, session_id: str, speaker_id: str, name: str) -> str:
        try:
            meeting = self._meeting.set_speaker_name(session_id, speaker_id, name)
            return json.dumps({"ok": True, "meeting": meeting}, ensure_ascii=False, default=str)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, int, str, result=str)
    def editMeetingSegment(self, session_id: str, index: int, text: str) -> str:
        try:
            meeting = self._meeting.edit_segment(session_id, index, text)
            return json.dumps({"ok": True, "meeting": meeting}, ensure_ascii=False, default=str)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, result=str)
    def deleteMeetingAudio(self, session_id: str) -> str:
        try:
            deleted = self._meeting.delete_audio(session_id)
            return json.dumps({"ok": True, "deleted": deleted}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, str, result=str)
    def exportMeetingFormat(self, session_id: str, format_name: str) -> str:
        try:
            meeting = self._meeting.get(session_id)
            if not meeting:
                raise KeyError("riunione non trovata")
            fmt = str(format_name or "txt").lower().lstrip(".")
            if fmt not in {"txt", "srt", "vtt"}:
                raise ValueError("formato riunione non supportato")
            target, _ = QFileDialog.getSaveFileName(
                None,
                "Esporta riunione",
                str(Path.home() / f"meeting-{session_id}.{fmt}"),
                {"txt": "Testo (*.txt)", "srt": "SubRip (*.srt)", "vtt": "WebVTT (*.vtt)"}[fmt],
            )
            if not target:
                return json.dumps({"ok": False, "cancelled": True}, ensure_ascii=False)
            exported = self._meeting.store.export(session_id, target, fmt)
            return json.dumps({"ok": True, "path": str(exported)}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    # ------------------------------------------------------------------
    # File batch / drag-and-drop
    # ------------------------------------------------------------------
    @Slot(result=str)
    def chooseAudioFiles(self) -> str:
        paths, _ = QFileDialog.getOpenFileNames(
            None,
            "Seleziona file audio o video",
            "",
            "Media (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.opus *.mp4 *.mkv *.webm *.mov *.avi);;Tutti i file (*)",
        )
        return json.dumps(paths, ensure_ascii=False)

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
            if self._meeting.is_busy():
                raise RuntimeError("Termina la riunione prima di accodare file")
            decoded = json.loads(paths_json)
            if not isinstance(decoded, list):
                raise ValueError("elenco file non valido")
            paths = [str(path) for path in decoded if str(path).strip()]
            jobs = self._file_batch.enqueue(
                paths,
                language=language.strip() or self._controller.settings.language,
                model_size=model_size.strip() or self._controller.settings.model_size,
                song_mode=bool(song_mode),
                isolate_vocals=bool(isolate_vocals),
            )
            return json.dumps({"ok": True, "jobs": jobs}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(result=str)
    def listFileQueue(self) -> str:
        return json.dumps(self._file_batch.list_jobs(), ensure_ascii=False, default=str)

    @Slot(result=str)
    def cancelFileQueue(self) -> str:
        jobs = self._file_batch.cancel(clear_pending=True)
        return json.dumps({"ok": True, "jobs": jobs}, ensure_ascii=False)

    @Slot(result=str)
    def clearFinishedFileQueue(self) -> str:
        jobs = self._file_batch.clear_finished()
        return json.dumps({"ok": True, "jobs": jobs}, ensure_ascii=False)

    def emitDroppedFiles(self, paths: list[str]) -> None:
        existing = [str(Path(path)) for path in paths if Path(path).is_file()]
        if existing:
            self._emit_event("file_drop_received", existing)

    # ------------------------------------------------------------------
    # History search/export/post-processing
    # ------------------------------------------------------------------
    @Slot(str, int, result=str)
    def searchHistory(self, query: str, limit: int = 100) -> str:
        self._controller.prune_history()
        return json.dumps(
            self._controller.history.search(query, max(1, min(int(limit), 500))),
            ensure_ascii=False,
            default=str,
        )

    @Slot(str, result=str)
    def getHistorySession(self, session_id: str) -> str:
        session = self._controller.get_history_session(session_id)
        if session and session.get("kind") == "meeting":
            session = self._meeting.get(session_id) or session
        return json.dumps(session, ensure_ascii=False, default=str)

    @Slot(str, str, result=str)
    def generatePostprocess(self, session_id: str, profile: str) -> str:
        try:
            session = self._controller.get_history_session(session_id)
            if not session:
                raise KeyError("sessione non trovata")
            derived = process_text(str(session.get("text") or ""), profile)
            self._controller.history.save_derived_output(session_id, profile, derived)
            self._emit_event("history_changed", session_id)
            return json.dumps(
                {"ok": True, "profile": profile, "text": derived},
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, str, str, result=str)
    def exportHistoryFormat(
        self,
        session_id: str,
        format_name: str,
        profile: str = "raw",
    ) -> str:
        try:
            session = self._controller.get_history_session(session_id)
            if not session:
                raise KeyError("sessione non trovata")
            fmt = str(format_name or "txt").strip().lower().lstrip(".")
            if fmt not in {"txt", "srt", "vtt"}:
                raise ValueError("formato export non supportato")
            if session.get("kind") == "meeting":
                target, _ = QFileDialog.getSaveFileName(
                    None,
                    "Esporta riunione",
                    str(Path.home() / f"meeting-{session_id}.{fmt}"),
                    {"txt": "Testo (*.txt)", "srt": "SubRip (*.srt)", "vtt": "WebVTT (*.vtt)"}[fmt],
                )
                if not target:
                    return json.dumps({"ok": False, "cancelled": True}, ensure_ascii=False)
                exported = self._meeting.store.export(session_id, target, fmt)
                return json.dumps({"ok": True, "path": str(exported)}, ensure_ascii=False)
            source_path = str(session.get("source_path") or "")
            stem = Path(source_path).stem if source_path else session_id
            default_path = str(Path.home() / f"{stem or session_id}.{fmt}")
            filters = {
                "txt": "Testo (*.txt)",
                "srt": "SubRip (*.srt)",
                "vtt": "WebVTT (*.vtt)",
            }
            target, _ = QFileDialog.getSaveFileName(
                None,
                "Esporta trascrizione",
                default_path,
                filters[fmt],
            )
            if not target:
                return json.dumps({"ok": False, "cancelled": True}, ensure_ascii=False)
            exported = self._controller.history.export_session(
                session_id,
                target,
                format_name=fmt,
                profile=profile or "raw",
            )
            return json.dumps({"ok": True, "path": str(exported)}, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Export cronologia %s fallito: %s", format_name, exc)
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot()
    def runAudioDiagnostics(self) -> None:
        def operation() -> None:
            report = build_audio_diagnostics(self._controller)
            self._emit_event("audio_diagnostics", report)

        self._run_async(
            "audio-diagnostics",
            operation,
            "audio_diagnostics_error",
        )

    @Slot()
    def stopLive(self) -> None:
        self.stopAllLive()

    @Slot()
    def stopListening(self) -> None:
        self.drainAllLive()
