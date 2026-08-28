"""Private persistence for XDG portal restoration state used by Dictation."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from config.constants import AppMeta


class DictationPortalStateStore:
    """Persist the opaque RemoteDesktop restore token outside public Settings.

    The token is native integration state, not a user preference. Keeping it in
    a dedicated private store prevents it from being serialized through the
    QWebChannel settings/bootstrap surface.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path or AppMeta.DICTATION_PORTAL_STATE_PATH)

    def restore_token(self) -> str | None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        value = data.get("remote_desktop_restore_token") if isinstance(data, dict) else None
        if not isinstance(value, str) or not value or len(value) > 8192:
            return None
        return value

    def set_restore_token(self, token: str | None) -> None:
        value = None if token is None else str(token)
        if value is not None and (not value or len(value) > 8192):
            raise ValueError("restore token RemoteDesktop non valido")
        if value is None:
            try:
                self._path.unlink(missing_ok=True)
            except OSError as exc:
                raise RuntimeError(f"Impossibile rimuovere lo stato portal: {exc}") from exc
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            dir=self._path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"remote_desktop_restore_token": value}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
