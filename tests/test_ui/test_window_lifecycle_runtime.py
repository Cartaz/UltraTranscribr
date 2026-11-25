from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from ui.main_window import clamp_window_geometry
from ui.tray_icon import TrayIcon

ROOT = Path(__file__).resolve().parents[2]


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_offscreen_saved_window_recovers_to_primary_screen() -> None:
    restored = clamp_window_geometry(
        QRect(2500, 2000, 1400, 900),
        [QRect(0, 0, 1920, 1040)],
    )

    assert restored == QRect(520, 140, 1400, 900)


def test_negative_coordinate_secondary_monitor_is_preserved() -> None:
    restored = clamp_window_geometry(
        QRect(-1500, 50, 1300, 820),
        [QRect(0, 0, 1920, 1040), QRect(-1600, 0, 1600, 900)],
    )

    assert restored == QRect(-1500, 50, 1300, 820)


def test_oversized_geometry_is_clamped_to_available_screen() -> None:
    restored = clamp_window_geometry(
        QRect(50, 40, 3000, 2000),
        [QRect(0, 0, 1920, 1040)],
    )

    assert restored == QRect(0, 0, 1920, 1040)


def test_tray_owns_context_menu_for_full_lifetime() -> None:
    _app()
    tray = TrayIcon()
    try:
        assert tray.contextMenu() is tray._menu
        assert tray.contextMenu() is not None
        assert not tray.ready_for_background()
    finally:
        tray.hide()


class _Tray:
    def __init__(self, ready: bool) -> None:
        self.ready = ready

    def ready_for_background(self) -> bool:
        return self.ready

    def set_running(self, _running) -> None:
        pass


def test_close_hides_to_ready_tray_and_otherwise_shuts_down(quick_window, monkeypatch):
    from unittest.mock import Mock

    from PySide6.QtGui import QCloseEvent

    import ui.main_window as main_window

    _app, window, _service, _controller, _messages = quick_window
    quit_app = Mock()
    monkeypatch.setattr(
        main_window.QApplication, "instance", staticmethod(lambda: quit_app)
    )
    monkeypatch.setattr(main_window.QTimer, "singleShot", lambda _ms, call: call())

    window.set_tray_icon(_Tray(ready=True))
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted() and not window._closing
    quit_app.quit.assert_not_called()

    window.set_tray_icon(_Tray(ready=False))
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted() and window._closing
    quit_app.quit.assert_called_once()


def test_unsaved_meeting_review_blocks_real_shutdown_until_confirmed(
    quick_window, monkeypatch
):
    from unittest.mock import Mock

    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    import ui.main_window as main_window

    _app, window, _service, _controller, _messages = quick_window
    quit_app = Mock()
    monkeypatch.setattr(
        main_window.QApplication, "instance", staticmethod(lambda: quit_app)
    )
    monkeypatch.setattr(main_window.QTimer, "singleShot", lambda _ms, call: call())
    window.set_tray_icon(_Tray(ready=False))
    window.runtime.meeting.dirtyChanged.emit(True)
    assert window._meeting_review_dirty
    monkeypatch.setattr(window.runtime.meeting, "_flush_drafts", lambda: False)
    answers = [QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Discard]
    monkeypatch.setattr(
        main_window.QMessageBox, "warning", staticmethod(lambda *a, **k: answers.pop(0))
    )

    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted() and not window._closing
    window.force_quit()
    assert window._closing
    quit_app.quit.assert_called_once()


def test_terminal_signals_route_through_qt_shutdown() -> None:
    import signal
    from unittest.mock import Mock

    import main

    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    app = _app()
    fake = Mock(wraps=None)
    fake.quit = Mock()
    try:
        timer = main.install_process_signal_handlers(app)
        timer.stop()
        assert timer.interval() == 250
        handler = signal.getsignal(signal.SIGTERM)
        assert signal.getsignal(signal.SIGINT) is handler
        original_quit = app.quit
        app.quit = fake.quit
        try:
            handler(signal.SIGTERM, None)
        finally:
            app.quit = original_quit
        fake.quit.assert_called_once()
    finally:
        for sig, value in previous.items():
            signal.signal(sig, value)


def test_move_and_resize_share_debounced_geometry_persistence(quick_window, monkeypatch):
    from unittest.mock import Mock

    from conftest import wait_until

    app, window, service, _controller, _messages = quick_window
    persist = Mock()
    monkeypatch.setattr(service, "persist_window_geometry", persist)
    wait_until(lambda: window._geometry_tracking_ready)
    window._window.resize(1300, 860)
    window._window.setPosition(40, 30)
    app.processEvents()
    assert persist.call_count == 0  # debounced, not one write per event
    wait_until(lambda: persist.call_count == 1, timeout=2000)
    _x, _y, width, height = persist.call_args.args
    assert (width, height) == (1300, 860)
