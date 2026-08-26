"""Native Qt/WebEngine smoke coverage for the real desktop shell."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


class _Application:
    def __init__(self) -> None:
        self.subscriptions: dict[str, list] = {}
        self.persisted_geometry: list[tuple[int, int]] = []

    def subscribe(self, event, handler) -> None:
        self.subscriptions.setdefault(event, []).append(handler)

    def preload_model_if_requested(self) -> None:
        return

    def existing_files(self, paths: list[str]) -> list[str]:
        return list(paths)

    def desktop_state(self) -> dict[str, object]:
        return {
            "window_width": 1200,
            "window_height": 800,
            "audio_source": "system",
            "sink_name": "",
            "language": "it",
            "live_active": False,
        }

    def persist_window_geometry(self, width: int, height: int) -> None:
        self.persisted_geometry.append((width, height))

    def live_active(self) -> bool:
        return False


def test_real_main_window_constructs_local_webengine_shell() -> None:
    app = QApplication.instance() or QApplication([])
    application = _Application()

    window = MainWindow(application)  # type: ignore[arg-type]
    app.processEvents()

    assert window.minimumWidth() == 1200
    assert window.minimumHeight() == 800
    assert window._web_view.url().isLocalFile()
    assert window._channel is not None
    assert window._bridge is not None

    window.close()
    app.processEvents()

    assert application.persisted_geometry[-1] == (1200, 800)
