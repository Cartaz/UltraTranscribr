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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from config.constants import AppMeta
from core.transcript_export import normalize_segments, render_export

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


def _clean_session_name(name: str) -> str:
    value = " ".join(str(name or "").split()).strip()
    if len(value) > 120:
        raise ValueError("Il nome della sessione non può superare 120 caratteri")
    return value


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
    name: str = ""
    ended_at: Optional[str] = None
    text: str = ""
    segments: list[dict[str, Any]] = field(default_factory=list)
    derived_outputs: dict[str, str] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        data = asdict(self)
        text = data.pop("text", "")
        segments = data.pop("segments", [])
        derived = data.pop("derived_outputs", {})
        compact = " ".join(text.split())
        data["text_preview"] = compact[:220]
        data["text_length"] = len(text)
        data["segment_count"] = len(segments)
        data["derived_profiles"] = sorted(derived)
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
        if kind not in {"live", "file", "meeting"}:
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

    def append_segments(self, session_id: str, segments: list[dict[str, Any]]) -> None:
        additions = normalize_segments(segments)
        if not additions:
            return
        with self._lock:
            session = self._read_session_required(session_id)
            session.segments = normalize_segments([*session.segments, *additions])
            session.updated_at = _utc_now()
            self._write_session(session)

    def save_derived_output(self, session_id: str, profile: str, text: str) -> None:
        key = str(profile or "").strip().lower()
        if not key:
            raise ValueError("profilo post-processing non valido")
        with self._lock:
            session = self._read_session_required(session_id)
            session.derived_outputs[key] = str(text or "")
            session.updated_at = _utc_now()
            self._write_session(session)

    def set_name(self, session_id: str, name: str) -> str:
        """Persist the optional display name in the canonical session record."""
        cleaned = _clean_session_name(name)
        with self._lock:
            session = self._read_session_required(session_id)
            session.name = cleaned
            session.updated_at = _utc_now()
            self._write_session(session)
        return cleaned

    def migrate_legacy_session_names(self, path: Optional[Path] = None) -> int:
        """Fold the former sidecar name store into canonical session records once."""
        legacy_path = Path(path or (AppMeta.DATA_DIR / "session-names.json"))
        if not legacy_path.is_file():
            return 0
        try:
            payload = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Migrazione nomi sessione ignorata: %s", exc)
            return 0
        if not isinstance(payload, dict):
            logger.warning("Migrazione nomi sessione ignorata: sidecar non valido")
            return 0

        migrated = 0
        with self._lock:
            for raw_id, raw_name in payload.items():
                session_id = str(raw_id or "").strip()
                if not session_id:
                    continue
                try:
                    session = self._read_session(session_id)
                    cleaned = _clean_session_name(str(raw_name or ""))
                except (ValueError, OSError):
                    logger.warning("Nome sessione legacy non valido ignorato: %s", session_id)
                    continue
                if session is None or not cleaned or session.name:
                    continue
                session.name = cleaned
                session.updated_at = _utc_now()
                self._write_session(session)
                migrated += 1

        try:
            legacy_path.unlink()
        except OSError as exc:
            logger.warning("Rimozione sidecar nomi sessione legacy fallita: %s", exc)
        return migrated

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
        return self._list_matching("", limit)

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Case-insensitive AND search over raw transcript and metadata."""
        return self._list_matching(str(query or ""), limit)

    def _list_matching(self, query: str, limit: int) -> list[dict[str, Any]]:
        wanted = max(1, min(int(limit), 500))
        terms = [term.casefold() for term in str(query or "").split() if term.strip()]
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
                if terms:
                    haystack = "\n".join(
                        (
                            session.text,
                            session.name,
                            session.source_path,
                            session.source,
                            session.model,
                            session.language,
                            session.kind,
                            session.status,
                        )
                    ).casefold()
                    if not all(term in haystack for term in terms):
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
        """Backward-compatible raw text export."""
        return self.export_session(session_id, target_path, format_name="txt")

    def export_session(
        self,
        session_id: str,
        target_path: Path | str,
        *,
        format_name: str = "txt",
        profile: str = "raw",
    ) -> Path:
        """Export raw/derived text or persisted timestamp segments atomically."""
        fmt = str(format_name or "txt").strip().lower().lstrip(".")
        if fmt not in {"txt", "srt", "vtt"}:
            raise ValueError(f"formato export non supportato: {format_name}")
        with self._lock:
            session = self._read_session_required(session_id)
            selected_text = session.text
            profile_key = str(profile or "raw").strip().lower()
            if profile_key != "raw":
                if profile_key not in session.derived_outputs:
                    raise KeyError(f"profilo non generato: {profile_key}")
                selected_text = session.derived_outputs[profile_key]
            content = render_export(
                text=selected_text,
                segments=session.segments,
                format_name=fmt,
            )
            target = Path(target_path).expanduser()
            if target.suffix.lower() != f".{fmt}":
                target = target.with_suffix(f".{fmt}")
            if not target.parent.is_dir():
                raise FileNotFoundError(f"directory di destinazione non trovata: {target.parent}")
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(content)
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
        # Older records predate name/timestamp/derived-output fields; dataclass
        # defaults keep them readable without migrations.
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
