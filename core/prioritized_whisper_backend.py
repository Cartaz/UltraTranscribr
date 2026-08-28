"""Priority-aware facade over the existing whisper-server lifecycle."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from config.constants import DictationDefaults
from config.settings import Settings
from core.inference_scheduler import InferencePriority, InferenceScheduler
from core.whisper_backend import WhisperBackend

logger = logging.getLogger(__name__)


class _PriorityBackendView:
    """Narrow transcription-only view with one fixed scheduling class."""

    def __init__(self, backend: "PrioritizedWhisperBackend", priority: InferencePriority) -> None:
        self._backend = backend
        self._priority = priority

    def transcribe_audio(self, *args: Any, **kwargs: Any) -> str | dict:
        kwargs.setdefault("priority", self._priority)
        return self._backend.transcribe_audio(*args, **kwargs)


class PrioritizedWhisperBackend:
    """Own the existing backend and arbitrate shared inference capacity.

    The wrapped :class:`WhisperBackend` remains the sole owner of subprocesses,
    HTTP requests and the multi-instance pool. This facade only decides which
    request may enter that capacity next; active inference is never preempted.
    """

    def __init__(self, settings: Settings, project_root: Optional[Path] = None) -> None:
        self._backend = WhisperBackend(settings, project_root)
        self._scheduler: InferenceScheduler[int] | None = None
        self._scheduler_capacity = 0
        self._scheduler_lock = threading.RLock()

    @property
    def server_url(self) -> str:
        return self._backend.server_url

    @property
    def is_running(self) -> bool:
        return self._backend.is_running

    @property
    def api_endpoint(self) -> str:
        return self._backend.api_endpoint

    @property
    def server_vad_enabled(self) -> bool:
        return self._backend.server_vad_enabled

    @property
    def instance_count(self) -> int:
        return self._backend.instance_count

    def start(self, model_path: Path, vad_model_path: Optional[Path] = None) -> None:
        self._close_scheduler()
        self._backend.start(model_path, vad_model_path)
        self._reset_scheduler()

    def ensure_vad_mode(self, enabled: bool, vad_model_path: Optional[Path] = None) -> None:
        wanted = bool(enabled and vad_model_path)
        if self.is_running and self.server_vad_enabled == wanted:
            return
        self._close_scheduler()
        try:
            self._backend.ensure_vad_mode(enabled, vad_model_path)
        finally:
            if self._backend.is_running:
                self._reset_scheduler()

    def reconfigure(self, settings: Settings) -> None:
        self._close_scheduler()
        self._backend.reconfigure(settings)

    def stop(self) -> None:
        self._close_scheduler()
        self._backend.stop()

    def abort_active_request(self) -> None:
        self._close_scheduler()
        self._backend.abort_active_request()

    def with_priority(self, priority: InferencePriority | str | int) -> _PriorityBackendView:
        return _PriorityBackendView(self, InferencePriority.coerce(priority))

    def transcribe_audio(
        self,
        audio_data: bytes,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        verbose: bool = False,
        *,
        timeout: Optional[float] = None,
        vad: Optional[bool] = None,
        on_queue_wait: Optional[Callable[[float], None]] = None,
        priority: InferencePriority | str | int = InferencePriority.LIVE,
    ) -> str | dict:
        if not self.is_running:
            raise RuntimeError("whisper-server non in esecuzione")
        scheduler = self._ensure_scheduler()
        token, wait_ms = scheduler.acquire(priority)
        if on_queue_wait is not None:
            try:
                on_queue_wait(wait_ms)
            except Exception:
                logger.exception("Callback metrica coda inferenza fallita")
        try:
            if not self.is_running:
                raise RuntimeError("whisper-server non in esecuzione")
            return self._backend.transcribe_audio(
                audio_data,
                language=language,
                prompt=prompt,
                verbose=verbose,
                timeout=timeout,
                vad=vad,
                on_queue_wait=None,
            )
        finally:
            scheduler.release(token)

    def _ensure_scheduler(self) -> InferenceScheduler[int]:
        with self._scheduler_lock:
            capacity = max(1, int(self.instance_count))
            scheduler = self._scheduler
            if scheduler is not None and not scheduler.closed and capacity == self._scheduler_capacity:
                return scheduler
            self._close_scheduler_locked()
            scheduler = InferenceScheduler(
                range(capacity),
                aging_seconds=DictationDefaults.SCHEDULER_AGING_S,
            )
            self._scheduler = scheduler
            self._scheduler_capacity = capacity
            return scheduler

    def _reset_scheduler(self) -> None:
        with self._scheduler_lock:
            self._close_scheduler_locked()
            if self.is_running:
                capacity = max(1, int(self.instance_count))
                self._scheduler = InferenceScheduler(
                    range(capacity),
                    aging_seconds=DictationDefaults.SCHEDULER_AGING_S,
                )
                self._scheduler_capacity = capacity

    def _close_scheduler(self) -> None:
        with self._scheduler_lock:
            self._close_scheduler_locked()

    def _close_scheduler_locked(self) -> None:
        scheduler = self._scheduler
        self._scheduler = None
        self._scheduler_capacity = 0
        if scheduler is not None:
            scheduler.close()
