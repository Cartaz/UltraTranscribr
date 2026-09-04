"""Persistent Meeting metadata layered beside the raw transcript history."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from config.constants import AppMeta
from core.speaker_diarization import speaker_label
from core.transcript_export import render_export
from core.transcript_history import TranscriptHistoryStore


class MeetingStore:
    def __init__(
        self,
        history: TranscriptHistoryStore,
        root: Optional[Path] = None,
    ) -> None:
        self.history = history
        self.root = Path(root or (AppMeta.DATA_DIR / "meetings"))
        self._lock = threading.RLock()

    def create(
        self,
        *,
        model: str,
        language: str,
        source: str,
        source_path: str,
        acquisition_mode: str = "realtime",
        num_speakers: int = 0,
    ) -> str:
        """Create one canonical Meeting record independent of acquisition method."""
        resolved_source = str(source or "").strip()
        if not resolved_source:
            raise ValueError("sorgente riunione non valida")
        resolved_path = str(source_path or "").strip()
        mode = str(acquisition_mode or "realtime").strip().lower()
        if mode not in {"realtime", "file"}:
            raise ValueError("modalità acquisizione riunione non valida")
        session_id = self.history.create_session(
            kind="meeting",
            model=model,
            language=language,
            source=resolved_source,
            source_path=resolved_path,
            status="recording" if mode == "realtime" else "preparing_file",
        )
        self._write(
            session_id,
            {
                "id": session_id,
                "recording": {},
                "acquisition": {
                    "mode": mode,
                    "sources": [],
                },
                "processing_status": "recording" if mode == "realtime" else "preparing_file",
                "num_speakers": max(0, int(num_speakers)),
                "diarization_segments": [],
                "speaker_names": {},
                "review_segments": [],
            },
        )
        return session_id

    def get(self, session_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            metadata = self._read(session_id)
        history = self.history.get_session(session_id)
        if metadata is None or history is None:
            return None
        metadata.setdefault("acquisition", {"mode": "realtime", "sources": []})
        return {**history, "meeting": metadata}

    def set_status(self, session_id: str, status: str, *, terminal: bool = False) -> None:
        with self._lock:
            data = self._require(session_id)
            data["processing_status"] = str(status)
            self._write(session_id, data)
        self.history.set_status(session_id, str(status), terminal=terminal)

    def set_recording(self, session_id: str, recording: dict[str, Any]) -> None:
        with self._lock:
            data = self._require(session_id)
            data["recording"] = dict(recording)
            self._write(session_id, data)

    def set_source_recordings(
        self,
        session_id: str,
        sources: list[dict[str, Any]],
    ) -> None:
        with self._lock:
            data = self._require(session_id)
            acquisition = dict(data.get("acquisition") or {})
            acquisition.setdefault("mode", "realtime")
            acquisition["sources"] = [dict(item) for item in sources]
            data["acquisition"] = acquisition
            self._write(session_id, data)

    def set_diarization(
        self,
        session_id: str,
        *,
        diarization_segments: list[dict[str, Any]],
        review_segments: list[dict[str, Any]],
        num_speakers: Optional[int] = None,
    ) -> None:
        with self._lock:
            data = self._require(session_id)
            data["diarization_segments"] = list(diarization_segments)
            data["review_segments"] = list(review_segments)
            if num_speakers is not None:
                data["num_speakers"] = max(0, int(num_speakers))
            self._write(session_id, data)

    def recording_path(self, session_id: str) -> Optional[Path]:
        """Return the validated canonical Meeting audio path when it still exists."""
        with self._lock:
            data = self._require(session_id)
            raw = str((data.get("recording") or {}).get("path") or "").strip()
        if not raw:
            return None
        try:
            return self._resolve_recording_path(raw, require_exists=True)
        except FileNotFoundError:
            return None

    def set_speaker_name(self, session_id: str, speaker_id: str, name: str) -> None:
        key = str(speaker_id or "").strip()
        if not key.startswith("SPEAKER_"):
            raise ValueError("speaker id non valido")
        with self._lock:
            data = self._require(session_id)
            names = dict(data.get("speaker_names") or {})
            cleaned = str(name or "").strip()
            if cleaned:
                names[key] = cleaned
            else:
                names.pop(key, None)
            data["speaker_names"] = names
            self._write(session_id, data)

    def edit_review_segment(self, session_id: str, index: int, text: str) -> None:
        with self._lock:
            data = self._require(session_id)
            segments = list(data.get("review_segments") or [])
            idx = int(index)
            if idx < 0 or idx >= len(segments):
                raise IndexError("segmento riunione non valido")
            item = dict(segments[idx])
            item["text"] = str(text or "").strip()
            segments[idx] = item
            data["review_segments"] = segments
            self._write(session_id, data)

    def delete_audio(self, session_id: str) -> bool:
        with self._lock:
            data = self._require(session_id)
            deleted = False
            for path in self._audio_paths(data, require_exists=False):
                try:
                    path.unlink()
                    deleted = True
                except FileNotFoundError:
                    continue
            data["recording"] = {}
            acquisition = dict(data.get("acquisition") or {})
            sources = []
            for item in acquisition.get("sources") or []:
                cleaned = dict(item)
                cleaned["recording"] = {}
                sources.append(cleaned)
            acquisition["sources"] = sources
            data["acquisition"] = acquisition
            self._write(session_id, data)
            return deleted

    def delete_sidecar(self, session_id: str) -> bool:
        with self._lock:
            path = self._path(session_id)
            try:
                path.unlink()
                return True
            except FileNotFoundError:
                return False

    def rendered_text(self, session_id: str) -> str:
        meeting = self.get(session_id)
        if meeting is None:
            raise KeyError("riunione non trovata")
        metadata = meeting["meeting"]
        names = dict(metadata.get("speaker_names") or {})
        lines: list[str] = []
        for item in metadata.get("review_segments") or []:
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            lines.append(f"{speaker_label(item.get('speaker_id'), names)}: {text}")
        return "\n\n".join(lines)

    def export(self, session_id: str, target: Path | str, fmt: str) -> Path:
        meeting = self.get(session_id)
        if meeting is None:
            raise KeyError("riunione non trovata")
        format_name = str(fmt or "txt").lower().lstrip(".")
        if format_name not in {"txt", "srt", "vtt"}:
            raise ValueError("formato riunione non supportato")
        metadata = meeting["meeting"]
        names = dict(metadata.get("speaker_names") or {})
        review = list(metadata.get("review_segments") or [])
        if format_name == "txt":
            content = self.rendered_text(session_id).rstrip() + "\n"
        else:
            segments = []
            for item in review:
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                label = speaker_label(item.get("speaker_id"), names)
                segments.append(
                    {
                        "start": item.get("start", 0.0),
                        "end": item.get("end", 0.0),
                        "text": f"{label}: {text}",
                    }
                )
            content = render_export(text="", segments=segments, format_name=format_name)
        path = Path(target).expanduser()
        if path.suffix.lower() != f".{format_name}":
            path = path.with_suffix(f".{format_name}")
        if not path.parent.is_dir():
            raise FileNotFoundError(path.parent)
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return path

    def prune_audio(self, retention_days: int) -> int:
        days = int(retention_days)
        if days <= 0 or not self.root.is_dir():
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        deleted_sessions = 0
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                audio_paths = self._audio_paths(data, require_exists=False)
                existing = [item for item in audio_paths if item.is_file()]
                if not existing:
                    continue
                newest = max(
                    datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
                    for item in existing
                )
                if newest >= cutoff:
                    continue
                for audio_path in existing:
                    audio_path.unlink()
                data["recording"] = {}
                acquisition = dict(data.get("acquisition") or {})
                sources = []
                for item in acquisition.get("sources") or []:
                    cleaned = dict(item)
                    cleaned["recording"] = {}
                    sources.append(cleaned)
                acquisition["sources"] = sources
                data["acquisition"] = acquisition
                self._atomic_json(path, data)
                deleted_sessions += 1
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return deleted_sessions

    def _audio_paths(
        self,
        data: dict[str, Any],
        *,
        require_exists: bool,
    ) -> list[Path]:
        raw_paths: list[str] = []
        recording = dict(data.get("recording") or {})
        if recording.get("path"):
            raw_paths.append(str(recording["path"]))
        acquisition = dict(data.get("acquisition") or {})
        for item in acquisition.get("sources") or []:
            source_recording = dict((item or {}).get("recording") or {})
            if source_recording.get("path"):
                raw_paths.append(str(source_recording["path"]))
        result: list[Path] = []
        seen: set[Path] = set()
        for raw in raw_paths:
            try:
                resolved = self._resolve_recording_path(raw, require_exists=require_exists)
            except FileNotFoundError:
                if require_exists:
                    raise
                continue
            if resolved not in seen:
                seen.add(resolved)
                result.append(resolved)
        return result

    @staticmethod
    def _resolve_recording_path(raw: str, *, require_exists: bool) -> Path:
        candidate = Path(raw).expanduser()
        root = AppMeta.RECORDINGS_DIR.expanduser().resolve()
        resolved = candidate.resolve(strict=require_exists)
        if resolved.parent != root or resolved.suffix.lower() != ".flac":
            raise ValueError("percorso registrazione non valido")
        return resolved

    def _path(self, session_id: str) -> Path:
        safe = str(session_id)
        if not safe or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in safe):
            raise ValueError("meeting id non valido")
        return self.root / f"{safe}.json"

    def _read(self, session_id: str) -> Optional[dict[str, Any]]:
        path = self._path(session_id)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None

    def _require(self, session_id: str) -> dict[str, Any]:
        data = self._read(session_id)
        if data is None:
            raise KeyError("riunione non trovata")
        return data

    def _write(self, session_id: str, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._atomic_json(self._path(session_id), data)

    @staticmethod
    def _atomic_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
