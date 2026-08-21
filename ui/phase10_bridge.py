"""Phase 10 WebChannel guardrails and retained-recording operations."""
from __future__ import annotations

import json

from PySide6.QtCore import QUrl, Slot

from config.settings import AudioSource
from core.session_recordings import delete_recording, recording_info
from ui.multi_session_bridge import MultiSessionBackendBridge


class Phase10BackendBridge(MultiSessionBackendBridge):
    """Keep Meeting exclusivity enforced below the JavaScript presentation."""

    def _meeting_busy_error(self, action: str) -> str | None:
        if not self._meeting.is_busy():
            return None
        return json.dumps(
            {"ok": False, "error": f"Termina la riunione prima di {action}"},
            ensure_ascii=False,
        )

    def _batch_busy(self) -> bool:
        return any(
            str(job.get("status")) in {"queued", "starting", "running"}
            for job in self._file_batch.list_jobs()
        )

    def _start_scoped_live(
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
        selection = str(selected_input or "").strip()
        lang = str(language or "").strip() or self._controller.settings.language
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

        should_record = bool(record_audio and source == AudioSource.MICROPHONE.value)
        session_settings = self._controller.settings.with_(
            language=lang,
            live_microphone_recording=should_record,
        )

        def operation() -> None:
            if self._meeting.is_busy():
                raise RuntimeError("Termina la riunione prima di avviare una sessione Live")
            if self._controller._file_busy():
                raise RuntimeError("Ferma la trascrizione File prima di avviare Live")
            self._prepare_backend_for_selected_model()
            self._controller.live_sessions.create_session(
                settings=session_settings,
                audio_source=source,
                sink_name=sink,
                language=lang,
                stream_id=stream_id,
            )

        self._run_async("start-live-phase10", operation, "live_session_start_error")

    @Slot(str, str, str)
    def startLive(self, audio_source: str, selected_input: str, language: str) -> None:
        self._start_scoped_live(audio_source, selected_input, language, False)

    @Slot(str, str, str, bool)
    def startLiveWithRecording(
        self,
        audio_source: str,
        selected_input: str,
        language: str,
        record_audio: bool,
    ) -> None:
        self._start_scoped_live(audio_source, selected_input, language, record_audio)

    @Slot(str, str, int, result=str)
    def startMeeting(self, microphone: str, language: str, num_speakers: int) -> str:
        if self._batch_busy():
            return json.dumps(
                {"ok": False, "error": "Annulla o completa la coda File prima di avviare una riunione"},
                ensure_ascii=False,
            )
        return super().startMeeting(microphone, language, num_speakers)

    @Slot(str, str, str, bool, bool)
    def startFile(
        self,
        file_path: str,
        language: str,
        model_size: str,
        song_mode: bool,
        isolate_vocals: bool,
    ) -> None:
        if self._meeting.is_busy():
            self._emit_event(
                "file_transcriber_error",
                "Termina la riunione prima di avviare una trascrizione File",
            )
            return
        super().startFile(
            file_path,
            language,
            model_size,
            song_mode,
            isolate_vocals,
        )

    @Slot(str, result=str)
    def startRecovery(self, recovery_path: str) -> str:
        blocked = self._meeting_busy_error("recuperare audio")
        if blocked:
            return blocked
        return super().startRecovery(recovery_path)

    @Slot(str, result=str)
    def downloadModel(self, model_size: str) -> str:
        blocked = self._meeting_busy_error("gestire i modelli")
        if blocked:
            return blocked
        return super().downloadModel(model_size)

    @Slot(str, result=str)
    def deleteModel(self, model_size: str) -> str:
        blocked = self._meeting_busy_error("gestire i modelli")
        if blocked:
            return blocked
        return super().deleteModel(model_size)

    @Slot(str, result=str)
    def applySettings(self, payload_json: str) -> str:
        blocked = self._meeting_busy_error("modificare le impostazioni")
        if blocked:
            return blocked
        return super().applySettings(payload_json)

    @Slot(str, result=str)
    def getSessionRecordingInfo(self, session_id: str) -> str:
        try:
            session = self._controller.get_history_session(session_id)
            if not session or session.get("kind") != "live" or session.get("source") != "microphone":
                return json.dumps({"exists": False, "session_id": session_id}, ensure_ascii=False)
            info = recording_info(session_id)
            if info.get("exists"):
                info["url"] = QUrl.fromLocalFile(str(info["path"])).toString()
            return json.dumps(info, ensure_ascii=False, default=str)
        except Exception as exc:
            return json.dumps({"exists": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, result=str)
    def deleteSessionRecording(self, session_id: str) -> str:
        try:
            runtime = self._controller.get_live_session(session_id)
            if runtime is not None and not bool(runtime.get("terminal")):
                raise RuntimeError("Ferma la sessione Live prima di eliminare la registrazione")
            session = self._controller.get_history_session(session_id)
            if not session or session.get("kind") != "live" or session.get("source") != "microphone":
                raise ValueError("La sessione non è una Live da microfono")
            deleted = delete_recording(session_id)
            self._emit_event("history_changed", session_id)
            return json.dumps({"ok": True, "deleted": deleted}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, result=str)
    def deleteHistorySession(self, session_id: str) -> str:
        session = self._controller.get_history_session(session_id)
        if session and session.get("kind") == "meeting":
            current = self._meeting.snapshot()
            if current and current.get("id") == session_id and self._meeting.is_busy():
                return json.dumps(
                    {"ok": False, "error": "Termina la riunione prima di eliminarla"},
                    ensure_ascii=False,
                )
        raw = super().deleteHistorySession(session_id)
        response = json.loads(raw)
        if not response.get("ok") or not response.get("deleted"):
            return raw
        try:
            if session and session.get("kind") == "meeting":
                try:
                    self._meeting.store.delete_audio(session_id)
                except Exception:
                    pass
                sidecar = self._meeting.store.root / f"{session_id}.json"
                sidecar.unlink(missing_ok=True)
            elif session and session.get("kind") == "live" and session.get("source") == "microphone":
                delete_recording(session_id)
        finally:
            self._emit_event("history_changed", session_id)
        return raw
