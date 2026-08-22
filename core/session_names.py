"""Persistent optional display names for transcript sessions."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Optional

from config.constants import AppMeta


class SessionNameStore:
    """Small atomic sidecar store keyed by transcript session id."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path or (AppMeta.DATA_DIR / "session-names.json"))
        self._lock = threading.RLock()

    @staticmethod
    def _clean_name(name: str) -> str:
        value = " ".join(str(name or "").split()).strip()
        if len(value) > 120:
            raise ValueError("Il nome della sessione non può superare 120 caratteri")
        return value

    def get(self, session_id: str) -> str:
        with self._lock:
            return str(self._read().get(str(session_id), ""))

    def set(self, session_id: str, name: str) -> str:
        key = str(session_id or "").strip()
        if not key:
            raise ValueError("session id non valido")
        value = self._clean_name(name)
        with self._lock:
            data = self._read()
            if value:
                data[key] = value
            else:
                data.pop(key, None)
            self._write(data)
        return value

    def delete(self, session_id: str) -> bool:
        key = str(session_id or "").strip()
        with self._lock:
            data = self._read()
            existed = key in data
            if existed:
                data.pop(key, None)
                self._write(data)
            return existed

    def apply(self, session: dict | None) -> dict | None:
        if not session:
            return session
        enriched = dict(session)
        enriched["name"] = self.get(str(enriched.get("id") or ""))
        return enriched

    def apply_many(self, sessions: list[dict]) -> list[dict]:
        with self._lock:
            names = self._read()
        result: list[dict] = []
        for session in sessions:
            enriched = dict(session)
            enriched["name"] = str(names.get(str(enriched.get("id") or ""), ""))
            result.append(enriched)
        return result

    def matching_ids(self, query: str) -> set[str]:
        terms = [term.casefold() for term in str(query or "").split() if term.strip()]
        if not terms:
            return set()
        with self._lock:
            names = self._read()
        return {
            session_id
            for session_id, name in names.items()
            if all(term in str(name).casefold() for term in terms)
        }

    def _read(self) -> dict[str, str]:
        if not self._path.is_file():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(k): str(v) for k, v in payload.items() if str(k).strip() and str(v).strip()}

    def _write(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".session-names.", suffix=".tmp", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self._path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
