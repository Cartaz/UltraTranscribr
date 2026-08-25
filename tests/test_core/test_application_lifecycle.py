"""Lifecycle contracts for the application boundary and desktop shell."""
from pathlib import Path

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

    def shutdown(self) -> None:
        self._events.append("controller")


class _FakeTasks:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def close(self) -> list[str]:
        self._events.append("tasks")
        return []


def test_application_service_owns_ordered_idempotent_shutdown() -> None:
    events: list[str] = []
    service = ApplicationService(_FakeController(events))  # type: ignore[arg-type]
    service._tasks = _FakeTasks(events)  # type: ignore[assignment]

    service.close()
    service.close()

    assert events == ["tasks", "controller"]


def test_presentation_and_composition_root_do_not_teardown_controller_directly() -> None:
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    window = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")

    assert "controller.shutdown()" not in main
    assert "self._controller.shutdown()" not in window
    assert "application.close()" in main
    assert "self._application.close()" in window
    assert "self.controller.shutdown()" in application
    assert "self._closed = False" in application
