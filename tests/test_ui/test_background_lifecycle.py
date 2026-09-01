from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_qapplication_stays_alive_when_window_closes_to_usable_tray():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "setQuitOnLastWindowClosed(False)" in source


def test_close_event_hides_only_to_ready_tray():
    source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "ready_for_background()" in source
    assert "self.hide()" in source
    assert "event.ignore()" in source
    assert "System tray non utilizzabile" in source


def test_explicit_quit_still_calls_application_quit():
    source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "def force_quit" in source
    assert "app.quit()" in source
