"""Phase 10 WebChannel guardrails and retained-recording operations."""
from __future__ import annotations

import json

from PySide6.QtCore import QUrl, Slot

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
