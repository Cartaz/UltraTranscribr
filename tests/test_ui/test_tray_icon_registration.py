from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_tray_prefers_stable_freedesktop_icon_name() -> None:
    source = (ROOT / "ui" / "tray_icon.py").read_text(encoding="utf-8")

    assert 'TRAY_ICON_NAME = "ultratranscribr"' in source
    assert "QIcon.fromTheme(TRAY_ICON_NAME)" in source
    assert 'icon.name() or "<pixmap>"' in source


def test_installer_registers_named_app_and_status_icons() -> None:
    script = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert 'DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"' in script
    assert 'scalable/apps/ultratranscribr.svg' in script
    assert 'scalable/status/ultratranscribr.svg' in script
    assert "Icon=ultratranscribr" in script
    assert "kbuildsycoca6 --noincremental" in script


def test_tray_icon_asset_is_font_independent_and_high_contrast() -> None:
    svg = (ROOT / "assets" / "icons" / "ultratranscribr.svg").read_text(
        encoding="utf-8"
    ).lower()

    assert "#ff6600" in svg
    assert "#141414" in svg
    assert "<text" not in svg
