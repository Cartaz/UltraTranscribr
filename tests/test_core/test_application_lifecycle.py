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

    assert events == [
        "unsubscribe:meeting_updated",
        "unsubscribe:history_changed",
        "tasks",
    ]


def test_application_service_releases_subscriptions_before_owned_tasks() -> None:
    events: list[str] = []
    controller = _FakeController(events)
    service = ApplicationService(controller)  # type: ignore[arg-type]
    service._tasks = _FakeTasks(events)  # type: ignore[assignment]
    handler = lambda _payload: None

    service.subscribe("live_session_updated", handler)
    service.close()

    assert controller.subscriptions == []
    assert events == [
        "unsubscribe:meeting_updated",
        "unsubscribe:history_changed",
        "unsubscribe:live_session_updated",
        "tasks",
    ]
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
    assert events == [
        "unsubscribe:history_changed",
        "unsubscribe:meeting_updated",
        "unsubscribe:history_changed",
    ]


def test_composition_root_owns_runtime_shutdown_after_application_cleanup(
    monkeypatch,
) -> None:
    """Run main() with recording fakes: UI first, application, then the core."""
    from unittest.mock import Mock

    import main
    from config.settings import Settings

    events: list[str] = []

    class _Recorder:
        def __init__(self, *args, **kwargs) -> None:
            self.__dict__.update(
                {name: Mock() for name in ("show", "raise_", "activateWindow", "on_start", "on_stop", "force_quit", "set_tray_icon", "setWindowIcon", "start", "log_readiness")}
            )
            for signal_name in ("show_window_requested", "quit_requested"):
                setattr(self, signal_name, Mock())

    class _Controller(_Recorder):
        def shutdown(self) -> None:
            events.append("controller.shutdown")

    class _Application(_Recorder):
        def close(self) -> None:
            events.append("application.close")

    class _Window(_Recorder):
        def dispose(self) -> None:
            events.append("window.dispose")

    class _Dictation(_Recorder):
        def close(self) -> None:
            events.append("dictation.close")

    class _Tray(_Recorder):
        def connect_start_action(self, _slot) -> None:
            pass

        def connect_stop_action(self, _slot) -> None:
            pass

    class _App:
        def __init__(self, _argv) -> None:
            pass

        def __getattr__(self, _name):
            return lambda *args, **kwargs: None

        def exec(self) -> int:
            events.append("app.exec")
            return 0

    monkeypatch.setattr(main, "setup_logging", lambda: None)
    monkeypatch.setattr(main.Settings, "load", classmethod(lambda cls: Settings()))
    monkeypatch.setattr(main, "QApplication", _App)
    monkeypatch.setattr(main, "install_process_signal_handlers", lambda app: Mock())
    monkeypatch.setattr(main.QTimer, "singleShot", lambda *args: None)
    monkeypatch.setattr(main, "QIcon", Mock())
    monkeypatch.setattr(main, "AppController", _Controller)
    monkeypatch.setattr(main, "ApplicationService", _Application)
    monkeypatch.setattr(main, "MainWindow", _Window)
    monkeypatch.setattr(main, "DictationNativeIntegration", _Dictation)
    monkeypatch.setattr(main, "TrayIcon", _Tray)

    with pytest.raises(SystemExit) as exited:
        main.main()
    assert exited.value.code == 0
    assert events == [
        "app.exec",
        "window.dispose",
        "dictation.close",
        "application.close",
        "controller.shutdown",
    ]
