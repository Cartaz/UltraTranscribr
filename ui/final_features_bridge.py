"""Final roadmap features layered over the Phase 10 WebChannel bridge."""
from __future__ import annotations

import json
import logging

from PySide6.QtCore import Slot

from core.session_names import SessionNameStore
from ui.phase10_bridge import Phase10BackendBridge

logger = logging.getLogger(__name__)


class FinalFeaturesBackendBridge(Phase10BackendBridge):
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
                self._run_async(
                    "preload-model",
                    controller.ensure_backend_started,
                    "backend_preload_error",
                )
            else:
                logger.info("Preload saltato: modello %s non installato", selected)

    def _named(self, session):
        return self._session_names.apply(session)

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
        response = json.loads(super().deleteHistorySession(session_id))
        if response.get("ok") and response.get("deleted"):
            self._session_names.delete(session_id)
        return json.dumps(response, ensure_ascii=False)
