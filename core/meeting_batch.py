"""Sequential batch queue for recorded Meeting workflows.

The coordinator owns only FIFO scheduling and queue state. Actual media
normalization, Whisper transcription, diarization and persistence remain owned by
MeetingManager, so batch and single-file meetings share exactly one processing
pipeline.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from core.background_tasks import BackgroundTaskGroup


class MeetingBatchManager(Protocol):
    """Narrow MeetingManager surface required by MeetingBatchCoordinator."""

    def subscribe(self, event: str, handler) -> None: ...

    def unsubscribe(self, event: str, handler) -> None: ...

    def is_busy(self) -> bool: ...

    def start_file(
        self,
        file_path: Path | str,
        *,
        language: str | None = None,
        model_size: str | None = None,
        num_speakers: int = 0,
    ) -> dict[str, Any]: ...

    def cancel(self) -> None: ...


@dataclass
class MeetingBatchJob:
    id: str
    path: str
    language: str
    model_size: str
    num_speakers: int
    status: str = "queued"
    phase: str = "queued"
    transcription_progress: int = 0
    diarization_progress: int = 0
    session_id: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MeetingBatchCoordinator:
    """Run recorded meetings serially while delegating each job to MeetingManager."""

    _ACTIVE_STATUSES = {"starting", "running", "cancelling"}
    _TERMINAL_PHASES = {"completed", "error", "cancelled", "interrupted"}

    def __init__(
        self,
        manager: MeetingBatchManager,
        *,
        event_sink: Callable[[str, Any], None],
    ) -> None:
        self._manager = manager
        self._event_sink = event_sink
        self._lock = threading.RLock()
        self._tasks = BackgroundTaskGroup("MeetingBatch", join_timeout=10.0)
        self._jobs: list[MeetingBatchJob] = []
        self._active_id: str | None = None
        self._closed = False
        self._subscriptions = (
            ("meeting_updated", self._on_meeting_updated),
            ("history_changed", self._on_history_changed),
        )
        for event, handler in self._subscriptions:
            self._manager.subscribe(event, handler)

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [job.to_dict() for job in self._jobs]

    def is_busy(self) -> bool:
        with self._lock:
            return any(
                job.status == "queued" or job.status in self._ACTIVE_STATUSES
                for job in self._jobs
            )

    def enqueue(
        self,
        paths: list[str],
        *,
        language: str,
        model_size: str,
        num_speakers: int,
    ) -> list[dict[str, Any]]:
        if self._closed:
            raise RuntimeError("coda riunioni chiusa")

        candidates: list[str] = []
        seen: set[str] = set()
        for raw in paths:
            path = Path(str(raw)).expanduser()
            if not path.is_file():
                raise FileNotFoundError(f"file non trovato: {path}")
            normalized = str(path)
            if normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(normalized)
        if not candidates:
            return self.list_jobs()

        count = int(num_speakers)
        if count < 0 or count > 20:
            raise ValueError("Il numero di interlocutori deve essere tra 0 e 20")

        with self._lock:
            for path in candidates:
                self._jobs.append(
                    MeetingBatchJob(
                        id=uuid.uuid4().hex[:12],
                        path=path,
                        language=str(language),
                        model_size=str(model_size),
                        num_speakers=count,
                    )
                )
        self._emit_changed()
        self._maybe_start_next_async()
        return self.list_jobs()

    def cancel(self, *, clear_pending: bool = True) -> list[dict[str, Any]]:
        should_cancel_runtime = False
        with self._lock:
            active = self._find(self._active_id)
            if active is not None and active.status in {"starting", "running"}:
                active.status = "cancelling"
                active.phase = "cancelling"
                active.error = ""
                should_cancel_runtime = bool(active.session_id)
            if clear_pending:
                for job in self._jobs:
                    if job.status == "queued":
                        job.status = "cancelled"
                        job.phase = "cancelled"
        if should_cancel_runtime:
            self._manager.cancel()
        self._emit_changed()
        return self.list_jobs()

    def clear_finished(self) -> list[dict[str, Any]]:
        with self._lock:
            self._jobs = [
                job
                for job in self._jobs
                if job.status == "queued" or job.status in self._ACTIVE_STATUSES
            ]
        self._emit_changed()
        return self.list_jobs()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        for event, handler in self._subscriptions:
            self._manager.unsubscribe(event, handler)
        self._tasks.close()

    def _maybe_start_next_async(self) -> None:
        with self._lock:
            if self._closed:
                return
        try:
            self._tasks.start("Start", self._maybe_start_next)
        except RuntimeError:
            return

    def _maybe_start_next(self) -> None:
        with self._lock:
            if self._closed or self._active_id is not None or self._manager.is_busy():
                return
            job = next((item for item in self._jobs if item.status == "queued"), None)
            if job is None:
                return
            job.status = "starting"
            job.phase = "preparing_file"
            self._active_id = job.id
        self._emit_job(job)
        self._emit_changed()

        try:
            snapshot = self._manager.start_file(
                job.path,
                language=job.language,
                model_size=job.model_size,
                num_speakers=job.num_speakers,
            )
        except Exception as exc:
            with self._lock:
                current = self._find(job.id)
                cancelled = current is not None and current.status == "cancelling"
            self._finish_active(
                "cancelled" if cancelled else "error",
                "" if cancelled else str(exc),
            )
            self._maybe_start_next_async()
            return

        cancel_after_start = False
        with self._lock:
            current = self._find(job.id)
            if current is None:
                return
            current.session_id = str(snapshot.get("id") or "")
            current.phase = str(snapshot.get("status") or "preparing_file")
            current.transcription_progress = self._progress(snapshot.get("progress"))
            current.diarization_progress = self._progress(
                snapshot.get("diarization_progress")
            )
            cancel_after_start = current.status == "cancelling"
            if not cancel_after_start:
                current.status = "running"
            job_snapshot = current.to_dict()
        self._emit_job_payload(job_snapshot)
        self._emit_changed()
        if cancel_after_start:
            self._manager.cancel()

    def _on_meeting_updated(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        session_id = str(payload.get("id") or "")
        with self._lock:
            active = self._find(self._active_id)
            if active is None or not active.session_id or active.session_id != session_id:
                return
            active.phase = str(payload.get("status") or active.phase)
            active.transcription_progress = self._progress(payload.get("progress"))
            active.diarization_progress = self._progress(
                payload.get("diarization_progress")
            )
            active.error = str(payload.get("error") or active.error)
            snapshot = active.to_dict()
        self._emit_job_payload(snapshot)
        self._emit_changed()

    def _on_history_changed(self, payload: Any) -> None:
        session_id = str(payload or "")
        with self._lock:
            active = self._find(self._active_id)
            if active is None or not active.session_id or active.session_id != session_id:
                return
            phase = active.phase
            error = active.error
        if phase not in self._TERMINAL_PHASES:
            return
        if phase == "completed":
            self._finish_active("completed")
        elif phase in {"cancelled", "interrupted"}:
            self._finish_active("cancelled")
        else:
            self._finish_active("error", error)
        self._maybe_start_next_async()

    def _finish_active(self, status: str, error: str = "") -> bool:
        with self._lock:
            active = self._find(self._active_id)
            if active is None:
                return False
            active.status = status
            active.phase = status
            if status == "completed":
                active.transcription_progress = 100
                active.diarization_progress = 100
            active.error = str(error or active.error)
            snapshot = active.to_dict()
            self._active_id = None
        self._emit_job_payload(snapshot)
        self._emit_changed()
        return True

    def _find(self, job_id: str | None) -> MeetingBatchJob | None:
        if not job_id:
            return None
        return next((job for job in self._jobs if job.id == job_id), None)

    @staticmethod
    def _progress(value: Any) -> int:
        try:
            return max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return 0

    def _emit_job(self, job: MeetingBatchJob) -> None:
        self._emit_job_payload(job.to_dict())

    def _emit_job_payload(self, payload: dict[str, Any]) -> None:
        self._event_sink("meeting_queue_job_updated", payload)

    def _emit_changed(self) -> None:
        self._event_sink("meeting_queue_changed", self.list_jobs())
