"""Passive end-to-end latency metrics for dictation validation."""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

Clock = Callable[[], float]


@dataclass(frozen=True)
class DictationMetricSample:
    activation_to_listening_ms: float | None
    activation_to_first_commit_ms: float | None
    activation_to_first_insert_ms: float | None
    finalization_ms: float | None
    max_queue_wait_ms: float

    def to_dict(self) -> dict[str, float | None]:
        return asdict(self)


class DictationMetricsTracker:
    """Observe dictation events without influencing the operational pipeline."""

    def __init__(self, *, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._activation_at: float | None = None
        self._listening_at: float | None = None
        self._first_commit_at: float | None = None
        self._first_insert_at: float | None = None
        self._finalizing_at: float | None = None
        self._max_queue_wait_ms = 0.0

    def observe(self, event: str, payload: Any) -> DictationMetricSample | None:
        now = self._clock()
        with self._lock:
            if event == "dictation_activation_changed" and bool((payload or {}).get("active")):
                self._start(now)
            elif event == "dictation_session_changed":
                status = str((payload or {}).get("status") or "")
                if status == "listening" and self._listening_at is None:
                    self._listening_at = now
                elif status == "finalizing" and self._finalizing_at is None:
                    self._finalizing_at = now
                elif status in {"idle", "error", "closed"} and self._activation_at is not None:
                    return self._finish(now)
            elif event == "dictation_text_committed" and self._first_commit_at is None:
                if str(payload or "").strip():
                    self._first_commit_at = now
            elif event == "dictation_text_inserted" and self._first_insert_at is None:
                if str(payload or "").strip():
                    self._first_insert_at = now
            elif event == "dictation_queue_wait":
                try:
                    self._max_queue_wait_ms = max(self._max_queue_wait_ms, float(payload or 0.0))
                except (TypeError, ValueError):
                    pass
        return None

    def _start(self, now: float) -> None:
        self._activation_at = now
        self._listening_at = None
        self._first_commit_at = None
        self._first_insert_at = None
        self._finalizing_at = None
        self._max_queue_wait_ms = 0.0

    def _finish(self, now: float) -> DictationMetricSample:
        assert self._activation_at is not None
        base = self._activation_at
        sample = DictationMetricSample(
            activation_to_listening_ms=self._delta(base, self._listening_at),
            activation_to_first_commit_ms=self._delta(base, self._first_commit_at),
            activation_to_first_insert_ms=self._delta(base, self._first_insert_at),
            finalization_ms=self._delta(self._finalizing_at, now) if self._finalizing_at is not None else None,
            max_queue_wait_ms=self._max_queue_wait_ms,
        )
        self._activation_at = None
        self._listening_at = None
        self._first_commit_at = None
        self._first_insert_at = None
        self._finalizing_at = None
        self._max_queue_wait_ms = 0.0
        return sample

    @staticmethod
    def _delta(start: float | None, end: float | None) -> float | None:
        if start is None or end is None:
            return None
        return max(0.0, (end - start) * 1000.0)


class DictationMetricsStore:
    """Append validation samples as JSONL behind one persistence boundary."""

    def __init__(self, path) -> None:
        from pathlib import Path
        self._path = Path(path)
        self._lock = threading.Lock()

    def append(self, sample: DictationMetricSample) -> None:
        import json
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(sample.to_dict(), ensure_ascii=False, sort_keys=True)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
