"""Lifecycle contracts for the application boundary and desktop shell."""
from pathlib import Path

import pytest

from core.application_service import ApplicationService


ROOT = Path(__file__).resolve().parents[2]


class _FakeHistory:
    def migrate_legacy_session_names(self) -> None:
        return None


class _FakeController:
    def __init__(self, events: list[str]) -> None:
        self.file_batch = object()
        self.meeting = object()
        self.history = _FakeHistory()
        self._events = events
        self.subscriptions: list[tuple[str, object]] = []

    def subscribe(self, event: str, handler) -> None:
        self.subscriptions.append((event, handler))

    def unsubscribe(self, event: str, handler) -> None:
        self._events.append(f"unsubscribe:{event}")
        subscription = (event, handler)
        if subscription in self.subscriptions:
            self.subscriptions.remove(subscription)

    def shutdown(self) -> None:
        self._events.append("controller")


class _FakeTasks:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def close(self) -> list[str]:
        self._events.append("tasks")
        return []


def test_application_service_owns_only_boundary_cleanup() -> None:
    events: list[str] = []
    service = ApplicationService(_FakeController(events))  # type: ignore[arg-type]
    service._tasks = _FakeTasks(events)  # type: ignore[assignment]

    service.close()
    service.close()

    assert events == ["tasks"]


def test_application_service_releases_subscriptions_before_owned_tasks() -> None:
    events: list[str] = []
    controller = _FakeController(events)
    service = ApplicationService(controller)  # type: ignore[arg-type]
    service._tasks = _FakeTasks(events)  # type: ignore[assignment]
    handler = lambda _payload: None

    service.subscribe("live_session_updated", handler)
    service.close()

    assert controller.subscriptions == []
    assert events == ["unsubscribe:live_session_updated", "tasks"]
    with pytest.raises(RuntimeError, match="chiuso"):
        service.subscribe("history_changed", handler)


def test_application_service_explicit_unsubscribe_updates_owned_registry() -> None:
    events: list[str] = []
    controller = _FakeController(events)
    service = ApplicationService(controller)  # type: ignore[arg-type]
    handler = lambda _payload: None

    service.subscribe("history_changed", handler)
    service.unsubscribe("history_changed", handler)
    service.close()

    assert controller.subscriptions == []
    assert events == ["unsubscribe:history_changed"]


def test_composition_root_owns_runtime_shutdown_after_application_cleanup() -> None:
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    window = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")

    assert "application.close()" in main
    assert "controller.shutdown()" in main
    assert main.index("application.close()") < main.index("controller.shutdown()")
    assert "self._application.close()" not in window
    assert "AppController" not in window
    assert "self.controller.shutdown()" not in application
    assert "self._closed = False" in application
    assert "self._subscriptions" in application
    assert "self.controller.unsubscribe(event, handler)" in application
