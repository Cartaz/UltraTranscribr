"""Priority scheduler for shared whisper-server capacity."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Generic, Iterable, TypeVar

T = TypeVar("T")
Clock = Callable[[], float]


class InferencePriority(IntEnum):
    """Lower values are served first under normal queueing."""

    INTERACTIVE = 0
    LIVE = 1
    BATCH = 2

    @classmethod
    def coerce(cls, value: "InferencePriority | str | int") -> "InferencePriority":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            mapping = {
                "interactive": cls.INTERACTIVE,
                "dictation": cls.INTERACTIVE,
                "live": cls.LIVE,
                "batch": cls.BATCH,
                "file": cls.BATCH,
            }
            if normalized in mapping:
                return mapping[normalized]
            raise ValueError(f"priorità inferenza non valida: {value}")
        return cls(int(value))


@dataclass(slots=True)
class _Waiter(Generic[T]):
    sequence: int
    priority: InferencePriority
    queued_at: float
    resource: T | None = None
    cancelled: bool = False


class InferenceScheduler(Generic[T]):
    """Allocate finite inference resources with priority and bounded starvation.

    Requests are FIFO inside the same effective priority. Waiting requests age
    by one priority level every ``aging_seconds`` so batch work cannot starve
    forever during sustained interactive traffic. Active requests are never
    preempted.
    """

    def __init__(
        self,
        resources: Iterable[T],
        *,
        aging_seconds: float = 30.0,
        clock: Clock = time.monotonic,
    ) -> None:
        available = list(resources)
        if not available:
            raise ValueError("lo scheduler richiede almeno una risorsa")
        if aging_seconds <= 0:
            raise ValueError("aging_seconds deve essere > 0")
        self._available = available
        self._aging_seconds = float(aging_seconds)
        self._clock = clock
        self._condition = threading.Condition()
        self._waiters: list[_Waiter[T]] = []
        self._sequence = 0
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._condition:
            return self._closed

    @property
    def queued_count(self) -> int:
        with self._condition:
            return sum(1 for item in self._waiters if not item.cancelled)

    def acquire(self, priority: InferencePriority | str | int) -> tuple[T, float]:
        requested = InferencePriority.coerce(priority)
        with self._condition:
            if self._closed:
                raise RuntimeError("scheduler inferenza chiuso")
            waiter = _Waiter[T](
                sequence=self._sequence,
                priority=requested,
                queued_at=self._clock(),
            )
            self._sequence += 1
            self._waiters.append(waiter)
            while True:
                if self._closed:
                    waiter.cancelled = True
                    self._remove_waiter(waiter)
                    raise RuntimeError("scheduler inferenza chiuso")
                if self._available and self._next_waiter() is waiter:
                    waiter.resource = self._available.pop(0)
                    self._remove_waiter(waiter)
                    waited_ms = max(0.0, (self._clock() - waiter.queued_at) * 1000.0)
                    return waiter.resource, waited_ms
                self._condition.wait(timeout=min(0.5, self._aging_seconds))

    def release(self, resource: T) -> None:
        with self._condition:
            if self._closed:
                return
            self._available.append(resource)
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()

    def _effective_priority(self, waiter: _Waiter[T]) -> int:
        waited = max(0.0, self._clock() - waiter.queued_at)
        promotions = int(waited // self._aging_seconds)
        return max(int(InferencePriority.INTERACTIVE), int(waiter.priority) - promotions)

    def _next_waiter(self) -> _Waiter[T] | None:
        active = [item for item in self._waiters if not item.cancelled]
        if not active:
            return None
        return min(active, key=lambda item: (self._effective_priority(item), item.sequence))

    def _remove_waiter(self, waiter: _Waiter[T]) -> None:
        try:
            self._waiters.remove(waiter)
        except ValueError:
            pass
