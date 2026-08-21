from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_window_size_inputs_expose_the_real_minimum() -> None:
    html = (ROOT / "ui" / "web" / "index.html").read_text(encoding="utf-8")
    assert 'name="window_width" type="number" min="1200"' in html
    assert 'name="window_height" type="number" min="800"' in html


def test_qt_shell_uses_shared_window_constraints() -> None:
    source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "UIConstraints.MIN_WINDOW_WIDTH" in source
    assert "UIConstraints.MIN_WINDOW_HEIGHT" in source
