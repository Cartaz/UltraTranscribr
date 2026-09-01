from pathlib import Path

from config.constants import UIConstraints


ROOT = Path(__file__).resolve().parents[2]


def test_window_geometry_is_not_manually_editable() -> None:
    html = (ROOT / "ui" / "web" / "index.html").read_text(encoding="utf-8")

    assert 'name="window_width"' not in html
    assert 'name="window_height"' not in html
    assert 'id="s-width" type="hidden" disabled' in html
    assert 'id="s-height" type="hidden" disabled' in html
    assert "Geometria automatica" in html


def test_qt_shell_enforces_and_persists_shared_window_constraints() -> None:
    shell = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")

    assert UIConstraints.MIN_WINDOW_WIDTH == 1200
    assert UIConstraints.MIN_WINDOW_HEIGHT == 800
    assert "UIConstraints.MIN_WINDOW_WIDTH" in shell
    assert "UIConstraints.MIN_WINDOW_HEIGHT" in shell
    assert "self.setMinimumSize(" in shell
    assert "def moveEvent" in shell
    assert "def resizeEvent" in shell
    assert "_persist_window_geometry" in shell
    assert "self._application.persist_window_geometry(" in shell
    assert "int(rect.x())" in shell
    assert "int(rect.y())" in shell
    assert "def persist_window_geometry(self, x: int, y: int, width: int, height: int)" in application
    for key in ("window_x", "window_y", "window_width", "window_height"):
        assert f'"{key}"' in application
