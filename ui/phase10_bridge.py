"""Unified WebChannel guardrails and retained-recording operations."""
from __future__ import annotations

import json
import logging

from PySide6.QtCore import QTimer, QUrl, Slot

from config.settings import AudioSource
from core.history_postprocess import generate_history_postprocess
from core.session_names import SessionNameStore
from core.session_recordings import delete_recording, recording_info
from ui.multi_session_bridge import MultiSessionBackendBridge

logger = logging.getLogger(__name__)


class Phase10BackendBridge(MultiSessionBackendBridge):
    """Presentation bridge with final workflow guardrails and history features."""

    def __init__(self, controller, parent=None) -> None:
        super().__init__(controller, parent)
        self._session_names = SessionNameStore()
        if controller.settings.preload_model:
            selected = controller.settings.model_size
            installed = any(
                str(item.get("id")) == selected and bool(item.get("installed"))
                for item in controller.list_models()
            )
            if installed:
                QTimer.singleShot(
                    0,
                    lambda: self._run_async(
                        "preload-model",
                        controller.ensure_backend_started,
                        "backend_preload_error",
                    ),
                )
            else:
                logger.info("Preload saltato: modello %s non installato", selected)

    def _named(self, session):
        return self._session_names.apply(session)

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

        def operation() -> None:
            if self._meeting.is_busy():
                raise RuntimeError("Termina la riunione prima di avviare una sessione Live")
            if self._controller.is_file_busy():
                raise RuntimeError("Ferma la trascrizione File prima di avviare Live")
            self._prepare_backend_for_selected_model()
            self._controller.start_live_session(
                sink_name=sink,
                audio_source=source,
                language=lang,
                stream_id=stream_id,
                record_audio=should_record,
            )

        self._run_async("start-live", operation, "live_session_start_error")

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
        super().startFile(file_path, language, model_size, song_mode, isolate_vocals)

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
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            return MultiSessionBackendBridge.applySettings(self, payload_json)
        if not isinstance(payload, dict):
            return MultiSessionBackendBridge.applySettings(self, payload_json)

        backend_keys = {
            "model_size",
            "beam_size",
            "vad_filter",
            "vad_min_silence_ms",
            "server_port",
            "gpu_layers",
            "compute_type",
            "backend_instances",
        }
        before = self._controller.settings
        backend_changed = any(
            key in payload and payload[key] != getattr(before, key, None)
            for key in backend_keys
        )
        if backend_changed and (
            self._controller.active_live_count() > 0
            or self._controller.is_file_busy()
        ):
            return json.dumps(
                {"ok": False, "error": "Ferma le trascrizioni attive prima di modificare il backend"},
                ensure_ascii=False,
            )

        raw = MultiSessionBackendBridge.applySettings(self, payload_json)
        response = json.loads(raw)
        if response.get("ok") and backend_changed:
            try:
                if self._controller.backend.is_running:
                    self._controller.stop_backend()
                self._controller.backend.reconfigure(self._controller.settings)
            except Exception as exc:
                logger.exception("Riconfigurazione backend fallita")
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        return raw

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

    @Slot(int, result=str)
    def listHistory(self, limit: int = 50) -> str:
        sessions = self._controller.list_history(max(1, min(int(limit), 500)))
        return json.dumps(self._session_names.apply_many(sessions), ensure_ascii=False, default=str)

    @Slot(str, int, result=str)
    def searchHistory(self, query: str, limit: int = 100) -> str:
        wanted = max(1, min(int(limit), 500))
        self._controller.prune_history()
        base = self._controller.history.search(query, wanted)
        by_id = {str(item.get("id")): item for item in base}
        name_ids = self._session_names.matching_ids(query)
        if name_ids and len(by_id) < wanted:
            for item in self._controller.history.list_recent(500):
                sid = str(item.get("id") or "")
                if sid in name_ids and sid not in by_id:
                    by_id[sid] = item
                    if len(by_id) >= wanted:
                        break
        sessions = list(by_id.values())[:wanted]
        return json.dumps(self._session_names.apply_many(sessions), ensure_ascii=False, default=str)

    @Slot(str, result=str)
    def getHistorySession(self, session_id: str) -> str:
        raw = json.loads(super().getHistorySession(session_id))
        return json.dumps(self._named(raw), ensure_ascii=False, default=str)

    @Slot(str, str, result=str)
    def generatePostprocess(self, session_id: str, profile: str) -> str:
        try:
            result = generate_history_postprocess(self._controller, session_id, profile)
            return json.dumps({"ok": True, **result}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, str, result=str)
    def renameHistorySession(self, session_id: str, name: str) -> str:
        try:
            if not self._controller.get_history_session(session_id):
                raise KeyError("sessione non trovata")
            cleaned = self._session_names.set(session_id, name)
            self._emit_event("history_changed", session_id)
            return json.dumps({"ok": True, "name": cleaned}, ensure_ascii=False)
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
        raw = MultiSessionBackendBridge.deleteHistorySession(self, session_id)
        response = json.loads(raw)
        if not response.get("ok") or not response.get("deleted"):
            return raw
        try:
            if session and session.get("kind") == "meeting":
                try:
                    self._meeting.store.delete_audio(session_id)
                except Exception as exc:
                    logger.warning("Rimozione audio meeting %s fallita: %s", session_id, exc)
                sidecar = self._meeting.store.root / f"{session_id}.json"
                sidecar.unlink(missing_ok=True)
            elif session and session.get("kind") == "live" and session.get("source") == "microphone":
                delete_recording(session_id)
            self._session_names.delete(session_id)
        finally:
            self._emit_event("history_changed", session_id)
        return raw
