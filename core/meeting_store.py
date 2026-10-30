"""Persistent Meeting metadata layered beside the raw transcript history."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from config.constants import AppMeta
from core.meeting_alignment import effective_speaker_id, speaker_label
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
                "processing_status": "recording"
                if mode == "realtime"
                else "preparing_file",
                "num_speakers": max(0, int(num_speakers)),
                "diarization_segments": [],
                "speaker_diarization_segments": [],
                "speaker_names": {},
                "review_segments": [],
            },
        )
        return session_id

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            metadata = self._read(session_id)
        history = self.history.get_session(session_id)
        if metadata is None or history is None:
            return None
        metadata.setdefault("acquisition", {"mode": "realtime", "sources": []})
        metadata.setdefault("speaker_diarization_segments", [])
        metadata["review_keys"] = [
            self._review_key(index, row)
            for index, row in enumerate(metadata.get("review_segments") or [])
        ]
        metadata["review_drafts"] = {}
        metadata["draft_conflicts"] = []
        try:
            checkpoint = self._read_drafts(session_id)
            metadata["draft_conflicts"] = list(checkpoint.get("conflicts") or [])
            drafts = checkpoint.get("edits", {})
            rows = metadata.get("review_segments") or []
            for raw_index, draft in drafts.items():
                index = int(raw_index)
                row = rows[index] if 0 <= index < len(rows) else None
                if (
                    row
                    and draft.get("review_key") == metadata["review_keys"][index]
                    and draft.get("base_text") == row.get("text", "")
                ):
                    metadata["review_drafts"][str(index)] = str(draft["text"])
                elif not row or draft.get("text") != row.get("text", ""):
                    metadata["draft_conflicts"].append({"index": index, **draft})
        except (OSError, ValueError, TypeError, KeyError) as exc:
            # A damaged draft must not hide the canonical transcript or be
            # silently discarded. Leave the file untouched for recovery.
            metadata["draft_recovery_error"] = f"Bozze non leggibili: {exc}"
        return {**history, "meeting": metadata}

    def set_status(
        self, session_id: str, status: str, *, terminal: bool = False
    ) -> None:
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

    def set_processing_pipeline(
        self, session_id: str, pipeline: str, provenance: dict[str, Any] | None = None
    ) -> None:
        if pipeline not in {"whisper", "english_qwen", "qwen_meeting"}:
            raise ValueError("percorso riunione non valido")
        with self._lock:
            data = self._require(session_id)
            data["processing_pipeline"] = {
                "id": pipeline,
                "provenance": dict(provenance or {}),
            }
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
        speaker_diarization_segments: Optional[list[dict[str, Any]]] = None,
        num_speakers: Optional[int] = None,
    ) -> None:
        with self._lock:
            data = self._require(session_id)
            data["diarization_segments"] = list(diarization_segments)
            if speaker_diarization_segments is not None:
                data["speaker_diarization_segments"] = list(
                    speaker_diarization_segments
                )
            data["review_segments"] = list(review_segments)
            if num_speakers is not None:
                data["num_speakers"] = max(0, int(num_speakers))
            self._write(session_id, data)

    def retain_original(
        self, session_id: str, source: Path, *, stop_event=None
    ) -> Path:
        """Copy the source bytes without re-encoding into managed retention storage."""
        with self._lock:
            self._require(session_id)
        source = Path(source)
        root = AppMeta.RECORDINGS_DIR
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"{session_id}-original{source.suffix.lower()}"
        temporary = target.with_suffix(target.suffix + ".tmp")
        digest = hashlib.sha256()
        try:
            with source.open("rb") as incoming, temporary.open("wb") as output:
                while block := incoming.read(1024 * 1024):
                    if stop_event is not None and stop_event.is_set():
                        raise RuntimeError("Conservazione originale annullata")
                    digest.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            with self._lock:
                data = self._require(session_id)
                data["original_recording"] = {
                    "path": str(target),
                    "size_bytes": target.stat().st_size,
                    "sha256": digest.hexdigest(),
                }
                self._write(session_id, data)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def playback_path(self, session_id: str) -> Optional[Path]:
        with self._lock:
            data = self._require(session_id)
            original = data.get("original_recording") or {}
        if not original.get("path"):
            return None
        try:
            path = self._resolve_original_path(original["path"])
            if not path.is_file() or path.stat().st_size != original.get("size_bytes"):
                return None
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                while block := handle.read(1024 * 1024):
                    digest.update(block)
            return path if digest.hexdigest() == original.get("sha256") else None
        except (OSError, ValueError, TypeError):
            # An unavailable original must not prevent opening the transcript.
            return None

    @staticmethod
    def _resolve_original_path(raw):
        path = Path(raw).expanduser().resolve()
        if (
            path.parent != AppMeta.RECORDINGS_DIR.expanduser().resolve()
            or "-original" not in path.name
        ):
            raise ValueError("percorso originale non valido")
        return path

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
            before = (data.get("speaker_names") or {}).get(key)
            data["speaker_names"] = names
            self._commit_review(
                session_id,
                data,
                [
                    {
                        "scope": "name",
                        "field": key,
                        "before": before,
                        "after": names.get(key),
                    }
                ],
            )

    def edit_review_segments(
        self,
        session_id: str,
        edits: dict[int, str],
    ) -> None:
        """Persist multiple review edits with one validated atomic sidecar write."""
        normalized = {int(index): str(text or "") for index, text in edits.items()}
        if not normalized:
            return
        with self._lock:
            data = self._require(session_id)
            segments = list(data.get("review_segments") or [])
            for idx in normalized:
                if idx < 0 or idx >= len(segments):
                    raise IndexError("segmento riunione non valido")

            changes = []
            for idx, text in normalized.items():
                item = dict(segments[idx])
                if str(item.get("text") or "") == text:
                    continue
                changes.append(
                    {
                        "scope": "segment",
                        "index": idx,
                        "field": "text",
                        "key": self._review_key(idx, item),
                        "before": item.get("text", ""),
                        "after": text,
                    }
                )
                item.setdefault("raw_text", str(item.get("text") or ""))
                item["text"] = text
                segments[idx] = item

            if not changes:
                return
            data["review_segments"] = segments
            self._commit_review(session_id, data, changes)

    def edit_review_segment(self, session_id: str, index: int, text: str) -> None:
        self.edit_review_segments(session_id, {int(index): text})

    def set_review_speaker_override(
        self,
        session_id: str,
        index: int,
        speaker_id: str,
    ) -> None:
        """Persist a manual review assignment without replacing model output."""
        override = str(speaker_id or "").strip()
        if override and not override.startswith("SPEAKER_"):
            raise ValueError("speaker id non valido")
        with self._lock:
            data = self._require(session_id)
            segments = list(data.get("review_segments") or [])
            idx = int(index)
            if idx < 0 or idx >= len(segments):
                raise IndexError("segmento riunione non valido")
            if override:
                known = {
                    str(item.get("speaker_id") or "")
                    for key in ("diarization_segments", "speaker_diarization_segments")
                    for item in data.get(key) or []
                    if str(item.get("speaker_id") or "")
                }
                known.update(str(key) for key in (data.get("speaker_names") or {}))
                if override not in known:
                    raise ValueError("speaker non presente nella riunione")
            item = dict(segments[idx])
            before = item.get("speaker_override")
            anchor = self._review_key(idx, item)
            if override:
                item["speaker_override"] = override
            else:
                item.pop("speaker_override", None)
            segments[idx] = item
            data["review_segments"] = segments
            self._commit_review(
                session_id,
                data,
                [
                    {
                        "scope": "segment",
                        "index": idx,
                        "key": anchor,
                        "field": "speaker_override",
                        "before": before,
                        "after": item.get("speaker_override"),
                    }
                ],
            )

    def _commit_review(self, session_id, data, changes):
        changes = [c for c in changes if c["before"] != c["after"]]
        if not changes:
            return
        data["review_undo"] = [*(data.get("review_undo") or []), changes][-500:]
        data["review_redo"] = []
        data["review_revision"] = int(data.get("review_revision", 0)) + 1
        self._write(session_id, data)

    def undo_review(self, session_id, *, redo=False):
        """Persist the command and its inverse together; delegates own no history.

        Anchors prevent applying old edits to unrelated rows after re-diarization.
        Storage failures leave the document and both stacks unchanged.
        """
        with self._lock:
            data = self._require(session_id)
            source, target = (
                ("review_redo", "review_undo")
                if redo
                else ("review_undo", "review_redo")
            )
            stack = list(data.get(source) or [])
            if not stack:
                return
            changes = stack.pop()
            rows = data.get("review_segments") or []
            for change in changes:
                if change["scope"] == "segment":
                    idx = change["index"]
                    if (
                        idx >= len(rows)
                        or self._review_key(idx, rows[idx]) != change["key"]
                    ):
                        raise ValueError(
                            "Interventi cambiati dopo il ricalcolo: annullamento non compatibile"
                        )
            for change in changes:
                value = change["after" if redo else "before"]
                item = (
                    data.setdefault("speaker_names", {})
                    if change["scope"] == "name"
                    else rows[change["index"]]
                )
                if value is None:
                    item.pop(change["field"], None)
                else:
                    item[change["field"]] = value
            data[source] = stack
            data[target] = [*(data.get(target) or []), changes][-500:]
            data["review_revision"] = int(data.get("review_revision", 0)) + 1
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
            data["original_recording"] = {}
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
            self._draft_path(session_id).unlink(missing_ok=True)
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
        blocks: list[tuple[Optional[str], list[str]]] = []
        for item in metadata.get("review_segments") or []:
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            speaker_id = effective_speaker_id(item)
            if speaker_id is not None and blocks and blocks[-1][0] == speaker_id:
                blocks[-1][1].append(text)
                continue
            blocks.append((speaker_id, [text]))

        lines = [
            f"{speaker_label(speaker_id, names)}: {' '.join(parts)}"
            for speaker_id, parts in blocks
        ]
        return "\n\n".join(lines)

    def export(self, session_id: str, target: Path | str, fmt: str) -> Path:
        meeting = self.get(session_id)
        if meeting is None:
            raise KeyError("riunione non trovata")
        format_name = str(fmt or "txt").lower().lstrip(".")
        if format_name not in {"txt", "srt"}:
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
                label = speaker_label(effective_speaker_id(item), names)
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
        fd, tmp = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
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
                data["original_recording"] = {}
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
        original = (data.get("original_recording") or {}).get("path")
        if original:
            result.append(self._resolve_original_path(original))
        seen: set[Path] = set(result)
        for raw in raw_paths:
            try:
                resolved = self._resolve_recording_path(
                    raw, require_exists=require_exists
                )
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
        if not safe or any(
            ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for ch in safe
        ):
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
        fd, tmp = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _draft_path(self, session_id: str) -> Path:
        return self.root / "review-drafts" / self._path(session_id).name

    def _read_drafts(self, session_id: str) -> dict[str, Any]:
        path = self._draft_path(session_id)
        if not path.exists():
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("edits"), dict):
            raise ValueError("formato bozze non valido")
        for index, draft in value["edits"].items():
            if (
                not str(index).isdigit()
                or not isinstance(draft, dict)
                or any(
                    not isinstance(draft.get(key), str)
                    for key in ("text", "base_text", "review_key")
                )
            ):
                raise ValueError("contenuto bozze non valido")
        conflicts = value.get("conflicts", [])
        if not isinstance(conflicts, list) or any(
            not isinstance(row, dict) for row in conflicts
        ):
            raise ValueError("conflitti bozze non validi")
        return value

    def save_review_drafts(self, session_id, edits, owner, revision) -> None:
        """Atomically checkpoint small UI drafts separately from approved text.

        A revision protects against an older background write finishing after
        the final shutdown checkpoint. Conflicting anchors are retained, not
        applied to an unrelated row after diarization changes its layout.
        """
        with self._lock:
            self._require(session_id)
            previous = self._read_drafts(session_id)
            if (
                previous.get("owner") == owner
                and int(previous.get("revision", -1)) > revision
            ):
                return
            normalized = {}
            for raw_index, draft in edits.items():
                index = int(raw_index)
                if index < 0 or not isinstance(draft, dict):
                    raise ValueError("bozza riunione non valida")
                normalized[str(index)] = {
                    key: str(draft[key]) for key in ("text", "base_text", "review_key")
                }
            rows = self._require(session_id).get("review_segments") or []
            conflicts = list(previous.get("conflicts") or [])
            for raw_index, draft in previous.get("edits", {}).items():
                index = int(raw_index)
                if not 0 <= index < len(rows) or draft.get(
                    "review_key"
                ) != self._review_key(index, rows[index]):
                    conflict = {"index": index, **draft}
                    if conflict not in conflicts:
                        conflicts.append(conflict)
            self._atomic_json(
                self._draft_path(session_id),
                {
                    "owner": str(owner),
                    "revision": int(revision),
                    "edits": normalized,
                    "conflicts": conflicts,
                },
            )

    @staticmethod
    def _review_key(index: int, row: dict[str, Any]) -> str:
        fields = [
            index,
            row.get("source_segment_index"),
            row.get("source_word_start"),
            row.get("source_word_end"),
            row.get("start"),
            row.get("end"),
            row.get("raw_text", row.get("text", "")),
        ]
        return hashlib.sha256(
            json.dumps(fields, ensure_ascii=False).encode()
        ).hexdigest()
