"""Partial composition failures must still release accepted service resources."""

from unittest.mock import MagicMock

import pytest

import main


def test_window_startup_failure_closes_service_before_controller(monkeypatch):
    calls = []
    app = MagicMock()
    controller = MagicMock()
    service = MagicMock()
    controller.shutdown.side_effect = lambda: calls.append("controller")
    service.close.side_effect = lambda: calls.append("application")
    monkeypatch.setattr(main, "setup_logging", lambda: None)
    monkeypatch.setattr(main, "QApplication", lambda args: app)
    monkeypatch.setattr(
        main, "install_process_signal_handlers", lambda app: MagicMock()
    )
    monkeypatch.setattr(main.Settings, "load", lambda: main.Settings())
    monkeypatch.setattr(main, "AppController", lambda **kwargs: controller)
    monkeypatch.setattr(main, "ApplicationService", lambda owner: service)

    def fail(**kwargs):
        raise RuntimeError("QML load failed")

    monkeypatch.setattr(main, "MainWindow", fail)
    with pytest.raises(RuntimeError, match="QML load failed"):
        main.main()
    assert calls == ["application", "controller"]
