"""Persistent, crash-resistant transcription history.

The web UI is intentionally not the source of truth for transcripts. This
module stores session text and metadata under XDG_DATA_HOME so a completed or
partially completed transcription survives a UI/app restart.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from config.constants import AppMeta

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class TranscriptSession:
    id: str
    kind: str
    started_at: str
    updated_at: str
    status: str
    model: str
    language: str
    source: str = ""
    source_path: str = ""
    ended_at: Optional[str] = None
    text: str = ""

    def summary(self) -> dict[str, Any]:
        data = asdict(self)
        text = data.pop("text", "")
        compact = " ".join(text.split())
        data["text_preview"] = compact[:220]
        data["text_length"] = len(text)
        return data


class TranscriptHistoryStore:
    """Thread-safe JSON session store using atomic file replacement."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self._root = Path(root or AppMeta.TRANSCRIPTS_DIR)
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        return self._root

    def create_session(
        self,
        *,
        kind: str,
        model: str,
        language: str,
        source: str = "",
        source_path: str = "",
        status: str = "starting",
    ) -> str:
        if kind not in {"live", "file"}:
            raise ValueError(f"kind non valido: {kind}")
        now = _utc_now()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        session_id = f"{stamp}-{uuid.uuid4().hex[:10]}"
        session = TranscriptSession(
            id=session_id,
            kind=kind,
            started_at=now,
            updated_at=now,
            status=status,
            model=model,
            language=language,
            source=source,
            source_path=source_path,
        )
        with self._lock:
            self._write_session(session)
        return session_id

    def append_text(self, session_id: str, text: str) -> None:
        addition = str(text or "").strip()
        if not addition:
            return
        with self._lock:
            session = self._read_session_required(session_id)
            session.text = (session.text.rstrip() + " " + addition).strip()
            session.updated_at = _utc_now()
            self._write_session(session)

    def replace_text(self, session_id: str, text: str) -> None:
        with self._lock:
            session = self._read_session_required(session_id)
            session.text = str(text or "").strip()
            session.updated_at = _utc_now()
            self._write_session(session)

    def set_status(self, session_id: str, status: str, *, terminal: bool = False) -> None:
        with self._lock:
            session = self._read_session_required(session_id)
            now = _utc_now()
            session.status = str(status)
            session.updated_at = now
            if terminal:
                session.ended_at = now
            self._write_session(session)

    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            session = self._read_session(session_id)
            return asdict(session) if session is not None else None

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        wanted = max(1, min(int(limit), 500))
        with self._lock:
            try:
                paths = sorted(
                    self._root.glob("*.json"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
            except OSError:
                return []
            sessions: list[dict[str, Any]] = []
            for path in paths:
                try:
                    session = self._read_path(path)
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    logger.warning("Cronologia illeggibile ignorata (%s): %s", path, exc)
                    continue
                sessions.append(session.summary())
                if len(sessions) >= wanted:
                    break
            return sessions

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            path = self._path(session_id)
            if not path.exists():
                return False
            path.unlink()
            return True

    def export_text(self, session_id: str, target_path: Path | str) -> Path:
        """Export only the transcript text, never rewriting the history record."""
        with self._lock:
            session = self._read_session_required(session_id)
            target = Path(target_path).expanduser()
            if target.suffix.lower() != ".txt":
                target = target.with_suffix(".txt")
            if not target.parent.is_dir():
                raise FileNotFoundError(f"directory di destinazione non trovata: {target.parent}")
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(session.text)
                    if session.text and not session.text.endswith("\n"):
                        handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, target)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
            return target

    def prune_older_than(self, retention_days: int) -> int:
        """Delete session records older than the configured retention period.

        A value of 0 disables automatic pruning.
        """
        days = int(retention_days)
        if days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = 0
        with self._lock:
            try:
                paths = list(self._root.glob("*.json"))
            except OSError:
                return 0
            for path in paths:
                try:
                    session = self._read_path(path)
                    timestamp = (
                        _parse_timestamp(session.ended_at)
                        or _parse_timestamp(session.updated_at)
                        or _parse_timestamp(session.started_at)
                    )
                    if timestamp is None or timestamp >= cutoff:
                        continue
                    path.unlink()
                    deleted += 1
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    logger.warning("Retention cronologia ignorata per %s: %s", path, exc)
        return deleted

    @staticmethod
    def list_recovery_audio(cache_dir: Optional[Path] = None) -> list[dict[str, Any]]:
        root = Path(cache_dir or AppMeta.CACHE_DIR)
        result: list[dict[str, Any]] = []
        try:
            paths = sorted(
                root.glob("recovery-live-*.wav"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return []
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                continue
            result.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(timespec="seconds"),
                }
            )
        return result

    @staticmethod
    def resolve_recovery_audio(path: Path | str, cache_dir: Optional[Path] = None) -> Path:
        root = Path(cache_dir or AppMeta.CACHE_DIR).expanduser().resolve()
        candidate = Path(path).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise FileNotFoundError(f"recovery audio non trovato: {candidate}") from exc
        if (
            resolved.parent != root
            or not resolved.name.startswith("recovery-live-")
            or resolved.suffix.lower() != ".wav"
        ):
            raise ValueError("percorso recovery non valido")
        if not resolved.is_file():
            raise FileNotFoundError(f"recovery audio non trovato: {resolved}")
        return resolved

    @classmethod
    def delete_recovery_audio(
        cls, path: Path | str, cache_dir: Optional[Path] = None
    ) -> bool:
        try:
            resolved = cls.resolve_recovery_audio(path, cache_dir)
        except FileNotFoundError:
            return False
        resolved.unlink()
        return True

    def _path(self, session_id: str) -> Path:
        safe_id = str(session_id)
        if not safe_id or any(
            ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for ch in safe_id
        ):
            raise ValueError("session id non valido")
        return self._root / f"{safe_id}.json"

    def _read_session_required(self, session_id: str) -> TranscriptSession:
        session = self._read_session(session_id)
        if session is None:
            raise KeyError(f"sessione non trovata: {session_id}")
        return session

    def _read_session(self, session_id: str) -> Optional[TranscriptSession]:
        path = self._path(session_id)
        if not path.is_file():
            return None
        try:
            return self._read_path(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("Sessione cronologia illeggibile (%s): %s", path, exc)
            return None

    @staticmethod
    def _read_path(path: Path) -> TranscriptSession:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("record cronologia non valido")
        return TranscriptSession(**data)

    def _write_session(self, session: TranscriptSession) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._path(session.id)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{session.id}.", suffix=".tmp", dir=self._root
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(asdict(session), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
