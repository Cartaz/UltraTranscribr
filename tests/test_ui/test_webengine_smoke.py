"""Native Qt/WebEngine smoke coverage for the real desktop shell."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from config.settings import Settings
from ui.main_window import MainWindow


class _Controller:
    def __init__(self) -> None:
        self.settings = Settings(window_width=1200, window_height=800)
        self.shutdown_calls = 0
        self.updated_settings: list[dict[str, int]] = []

    def active_live_count(self) -> int:
        return 0

    def update_settings(self, **overrides) -> None:
        self.updated_settings.append(overrides)
        self.settings = self.settings.with_(**overrides)

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _Application:
    def __init__(self, controller: _Controller) -> None:
        self.closed = 0
        self.subscriptions: dict[str, list] = {}
        self.controller = controller

    def subscribe(self, event, handler) -> None:
        self.subscriptions.setdefault(event, []).append(handler)

    def preload_model_if_requested(self) -> None:
        return

    def existing_files(self, paths: list[str]) -> list[str]:
        return list(paths)

    def close(self) -> None:
        self.closed += 1
        self.controller.shutdown()


def test_real_main_window_constructs_local_webengine_shell() -> None:
    app = QApplication.instance() or QApplication([])
    controller = _Controller()
    application = _Application(controller)

    window = MainWindow(controller, application)
    app.processEvents()

    assert window.minimumWidth() == 1200
    assert window.minimumHeight() == 800
    assert window._web_view.url().isLocalFile()
    assert window._channel is not None
    assert window._bridge is not None

    window.close()
    app.processEvents()

    assert application.closed == 1
    assert controller.shutdown_calls == 1
