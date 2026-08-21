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
        microphone: str,
        num_speakers: int = 0,
    ) -> str:
        # Reuse the history store's ID generation and atomic schema, then only
        # change the kind. TranscriptSession itself accepts arbitrary kind values
        # when reading existing records, so older clients still degrade safely.
        session_id = self.history.create_session(
            kind="file",
            model=model,
            language=language,
            source="microphone",
            source_path=microphone,
            status="recording",
        )
        history_path = self.history.root / f"{session_id}.json"
        payload = json.loads(history_path.read_text(encoding="utf-8"))
        payload["kind"] = "meeting"
        self._atomic_json(history_path, payload)
        self._write(
            session_id,
            {
                "id": session_id,
                "recording": {},
                "processing_status": "recording",
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

    def set_diarization(
        self,
        session_id: str,
        *,
        diarization_segments: list[dict[str, Any]],
        review_segments: list[dict[str, Any]],
    ) -> None:
        with self._lock:
            data = self._require(session_id)
            data["diarization_segments"] = list(diarization_segments)
            data["review_segments"] = list(review_segments)
            self._write(session_id, data)

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
            recording = dict(data.get("recording") or {})
            raw = str(recording.get("path") or "")
            deleted = False
            if raw:
                path = Path(raw).expanduser()
                try:
                    resolved = path.resolve(strict=True)
                    root = AppMeta.RECORDINGS_DIR.expanduser().resolve()
                    if resolved.parent != root:
                        raise ValueError("percorso registrazione non valido")
                    resolved.unlink()
                    deleted = True
                except FileNotFoundError:
                    deleted = False
            data["recording"] = {}
            self._write(session_id, data)
            return deleted

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
        deleted = 0
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                recording = dict(data.get("recording") or {})
                audio_path = Path(str(recording.get("path") or ""))
                if not audio_path.is_file():
                    continue
                modified = datetime.fromtimestamp(audio_path.stat().st_mtime, tz=timezone.utc)
                if modified >= cutoff:
                    continue
                audio_path.unlink()
                data["recording"] = {}
                self._atomic_json(path, data)
                deleted += 1
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return deleted

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
