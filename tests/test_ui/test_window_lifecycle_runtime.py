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


def test_close_path_requires_explicit_tray_readiness_contract() -> None:
    source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert "ready_for_background()" in source
    assert "System tray non utilizzabile" in source
    assert "self.hide()" in source
    assert "app.quit()" in source


def test_terminal_signals_route_through_qt_shutdown() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")

    assert "signal.SIGINT" in source
    assert "signal.SIGTERM" in source
    assert "install_process_signal_handlers(app)" in source
    assert "timer.setInterval(250)" in source


def test_move_and_resize_share_debounced_geometry_persistence() -> None:
    source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert "def moveEvent" in source
    assert "def resizeEvent" in source
    assert source.count("self._schedule_geometry_save()") >= 2
    assert "self._application.persist_window_geometry(" in source
