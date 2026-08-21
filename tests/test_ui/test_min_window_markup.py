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
    source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert UIConstraints.MIN_WINDOW_WIDTH == 1200
    assert UIConstraints.MIN_WINDOW_HEIGHT == 800
    assert "UIConstraints.MIN_WINDOW_WIDTH" in source
    assert "UIConstraints.MIN_WINDOW_HEIGHT" in source
    assert "self.setMinimumSize(" in source
    assert "def resizeEvent" in source
    assert "_persist_window_geometry" in source
    assert "window_width=width" in source
    assert "window_height=height" in source
