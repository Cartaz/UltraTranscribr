"""Sequential batch queue layered on the existing single File worker."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional, Protocol

from config.settings import Settings
from core.background_tasks import BackgroundTaskGroup
from core.event_bus import EventBus


class FileBatchController(Protocol):
    """Small application contract required by FileBatchCoordinator."""

    @property
    def settings(self) -> Settings: ...

    def subscribe(self, event: str, handler) -> None: ...

    def unsubscribe(self, event: str, handler) -> None: ...

    def active_live_count(self) -> int: ...

    def is_file_transcribing(self) -> bool: ...

    def start_file_transcription(
        self,
        file_path: str,
        language: Optional[str] = None,
        model_size: Optional[str] = None,
        song_mode: bool = False,
        isolate_vocals_flag: bool = False,
        history_source: str = "file",
    ) -> None: ...

    def stop_file_transcription(self) -> None: ...


@dataclass
class FileBatchJob:
    id: str
    path: str
    language: str
    model_size: str
    song_mode: bool = False
    isolate_vocals: bool = False
    status: str = "queued"
    progress: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FileBatchCoordinator:
    """Own a FIFO queue while reusing the public File lifecycle."""

    _WORKER_EXIT_TIMEOUT_S = 10.0
    _WORKER_EXIT_POLL_S = 0.05

    def __init__(self, controller: FileBatchController) -> None:
        self._controller = controller
        self._bus = EventBus()
        self._lock = threading.RLock()
        self._tasks = BackgroundTaskGroup("FileBatch", join_timeout=10.0)
        self._jobs: list[FileBatchJob] = []
        self._active_id: Optional[str] = None
        self._closed = False
        self._subscriptions = (
            ("file_transcriber_progress", self._on_progress),
            ("file_transcriber_completed", self._on_completed),
            ("file_transcriber_error", self._on_error),
            ("file_transcriber_status_changed", self._on_status),
        )
        for event, handler in self._subscriptions:
            self._controller.subscribe(event, handler)

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [job.to_dict() for job in self._jobs]

    def enqueue(
        self,
        paths: list[str],
        *,
        language: str,
        model_size: str,
        song_mode: bool = False,
        isolate_vocals: bool = False,
    ) -> list[dict[str, Any]]:
        if self._closed:
            raise RuntimeError("coda file chiusa")
        if self._controller.active_live_count() > 0:
            raise RuntimeError("Ferma le sessioni Live prima di accodare file")

        candidates: list[str] = []
        for raw in paths:
            path = Path(str(raw)).expanduser()
            if not path.is_file():
                raise FileNotFoundError(f"file non trovato: {path}")
            candidates.append(str(path))
        if not candidates:
            return self.list_jobs()

        with self._lock:
            for path in candidates:
                self._jobs.append(
                    FileBatchJob(
                        id=uuid.uuid4().hex[:12],
                        path=path,
                        language=str(language or self._controller.settings.language),
                        model_size=str(model_size or self._controller.settings.model_size),
                        song_mode=bool(song_mode),
                        isolate_vocals=bool(isolate_vocals and song_mode),
                    )
                )
        self._emit_changed()
        self._maybe_start_next_async()
        return self.list_jobs()

    def cancel(self, *, clear_pending: bool = True) -> list[dict[str, Any]]:
        with self._lock:
            active = self._find(self._active_id)
            if active is not None and active.status in {"starting", "running"}:
                active.status = "cancelled"
                active.error = ""
            self._active_id = None
            if clear_pending:
                for job in self._jobs:
                    if job.status == "queued":
                        job.status = "cancelled"
        self._controller.stop_file_transcription()
        self._emit_changed()
        return self.list_jobs()

    def clear_finished(self) -> list[dict[str, Any]]:
        with self._lock:
            self._jobs = [
                job
                for job in self._jobs
                if job.status in {"queued", "starting", "running"}
            ]
        self._emit_changed()
        return self.list_jobs()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        for event, handler in self._subscriptions:
            self._controller.unsubscribe(event, handler)
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
            if self._closed or self._active_id is not None:
                return
            if self._controller.active_live_count() > 0:
                return
            if self._controller.is_file_transcribing():
                return
            job = next((item for item in self._jobs if item.status == "queued"), None)
            if job is None:
                return
            job.status = "starting"
            self._active_id = job.id
            snapshot = job.to_dict()
        self._bus.emit("file_queue_job_updated", snapshot)
        self._emit_changed()

        try:
            self._controller.start_file_transcription(
                job.path,
                language=job.language,
                model_size=job.model_size,
                song_mode=job.song_mode,
                isolate_vocals_flag=job.isolate_vocals,
                history_source="batch",
            )
        except Exception as exc:
            self._finish_active("error", str(exc))
            self._maybe_start_next_async()
            return

        with self._lock:
            current = self._find(job.id)
            if current is not None and current.status == "starting":
                current.status = "running"
        self._emit_changed()

    def _on_progress(self, payload: Any) -> None:
        with self._lock:
            active = self._find(self._active_id)
            if active is None:
                return
            try:
                active.progress = max(0, min(100, int(payload)))
            except (TypeError, ValueError):
                return
            snapshot = active.to_dict()
        self._bus.emit("file_queue_job_updated", snapshot)
        self._emit_changed()

    def _on_completed(self, _payload: Any) -> None:
        if self._finish_active("completed") or self._has_pending():
            self._advance_after_worker()

    def _on_error(self, payload: Any) -> None:
        if self._finish_active("error", str(payload or "")) or self._has_pending():
            self._advance_after_worker()

    def _on_status(self, payload: Any) -> None:
        if str(payload) != "stopped":
            return
        if self._finish_active("cancelled") or self._has_pending():
            self._advance_after_worker()

    def _finish_active(self, status: str, error: str = "") -> bool:
        with self._lock:
            active = self._find(self._active_id)
            if active is None:
                return False
            active.status = status
            active.progress = 100 if status == "completed" else active.progress
            active.error = error
            snapshot = active.to_dict()
            self._active_id = None
        self._bus.emit("file_queue_job_updated", snapshot)
        self._emit_changed()
        return True

    def _has_pending(self) -> bool:
        with self._lock:
            return any(job.status == "queued" for job in self._jobs)

    def _advance_after_worker(self) -> None:
        def advance() -> None:
            deadline = time.monotonic() + self._WORKER_EXIT_TIMEOUT_S
            while self._controller.is_file_transcribing():
                with self._lock:
                    if self._closed:
                        return
                if time.monotonic() >= deadline:
                    return
                time.sleep(self._WORKER_EXIT_POLL_S)
            self._maybe_start_next()

        with self._lock:
            if self._closed:
                return
        try:
            self._tasks.start("Advance", advance)
        except RuntimeError:
            return

    def _find(self, job_id: Optional[str]) -> Optional[FileBatchJob]:
        if not job_id:
            return None
        return next((job for job in self._jobs if job.id == job_id), None)

    def _emit_changed(self) -> None:
        self._bus.emit("file_queue_changed", self.list_jobs())
