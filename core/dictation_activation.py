"""Canonical activation state for system-wide dictation."""
from __future__ import annotations

import threading
from typing import Any, Callable

EventSink = Callable[[str, Any], None]


class DictationActivationService:
    """Translate shortcut press/release edges into one canonical active flag."""

    MODES = {"push_to_talk", "toggle"}

    def __init__(self, mode: str = "push_to_talk", *, event_sink: EventSink | None = None) -> None:
        self._lock = threading.RLock()
        self._event_sink = event_sink
        self._mode = self._validate_mode(mode)
        self._active = False
        self._pressed = False
        self._closed = False

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mode": self._mode,
                "active": self._active,
                "pressed": self._pressed,
                "closed": self._closed,
            }

    def set_mode(self, mode: str) -> None:
        value = self._validate_mode(mode)
        activation_changed = False
        with self._lock:
            if self._closed or value == self._mode:
                return
            self._mode = value
            self._pressed = False
            if self._active:
                self._active = False
                activation_changed = True
        self._emit("dictation_activation_mode_changed", value)
        if activation_changed:
            self._emit("dictation_activation_changed", self.snapshot())

    def press(self) -> None:
        changed = False
        with self._lock:
            if self._closed or self._pressed:
                return
            self._pressed = True
            if self._mode == "toggle":
                self._active = not self._active
                changed = True
            elif not self._active:
                self._active = True
                changed = True
        if changed:
            self._emit("dictation_activation_changed", self.snapshot())

    def release(self) -> None:
        changed = False
        with self._lock:
            if self._closed or not self._pressed:
                return
            self._pressed = False
            if self._mode == "push_to_talk" and self._active:
                self._active = False
                changed = True
        if changed:
            self._emit("dictation_activation_changed", self.snapshot())

    def cancel(self) -> None:
        changed = False
        with self._lock:
            if self._closed:
                return
            self._pressed = False
            if self._active:
                self._active = False
                changed = True
        if changed:
            self._emit("dictation_activation_changed", self.snapshot())

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._pressed = False
            self._active = False
        self._emit("dictation_activation_changed", self.snapshot())

    @classmethod
    def _validate_mode(cls, mode: str) -> str:
        value = str(mode or "").strip().lower()
        if value not in cls.MODES:
            raise ValueError(f"modalità attivazione dettatura non valida: {mode}")
        return value

    def _emit(self, event: str, payload: Any) -> None:
        if self._event_sink is not None:
            self._event_sink(event, payload)
