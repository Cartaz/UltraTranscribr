"""Contracts for settings grouping, resets and window geometry."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "ui" / "web"


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_settings_are_split_into_normal_and_advanced_panes() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")

    assert 'data-settings-tab="normal"' in html
    assert 'data-settings-tab="advanced"' in html
    assert 'data-settings-pane="normal"' in html
    assert 'data-settings-pane="advanced"' in html

    normal = _between(html, 'data-settings-pane="normal"', 'data-settings-pane="advanced"')
    for field in ("model_size", "language", "audio_source", "vad_filter"):
        assert f'name="{field}"' in normal
    for field in ("beam_size", "chunk_ms", "sink_name", "server_port", "gpu_layers", "compute_type"):
        assert f'name="{field}"' not in normal

    advanced = html.split('data-settings-pane="advanced"', 1)[1]
    for field in ("beam_size", "chunk_ms", "sink_name", "server_port", "gpu_layers", "compute_type"):
        assert f'name="{field}"' in advanced


def test_manual_window_geometry_fields_are_removed_from_settings_payload() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "settings_cleanup.js").read_text(encoding="utf-8")

    assert 'name="window_width"' not in html
    assert 'name="window_height"' not in html
    assert "Geometria automatica" in html
    assert 'element.name === "window_width"' in script
    assert 'element.name === "window_height"' in script


def test_each_settings_group_has_a_scoped_reset() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "settings_cleanup.js").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")

    for section in ("recognition", "history", "tuning", "audio", "backend"):
        assert f'data-reset-section="{section}"' in html
        assert f"{section}:" in script

    assert "resetSettingsSection" in script
    assert "getSettingsDefaults" in script
    assert "getSettingsDefaults" in bridge
    assert "asdict(Settings())" in application
    assert "sessionBusy()" in script


def test_window_geometry_is_persisted_automatically_with_debounce() -> None:
    main_window = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")

    assert "QTimer" in main_window
    assert "def resizeEvent" in main_window
    assert "_geometry_save_timer.start(350)" in main_window
    assert "_persist_window_geometry" in main_window
    assert "self._application.persist_window_geometry(width, height)" in main_window
    assert "UIConstraints.MIN_WINDOW_WIDTH" in main_window
    assert "UIConstraints.MIN_WINDOW_HEIGHT" in main_window
    assert "def persist_window_geometry" in application
    assert "window_width=width" in application
    assert "window_height=height" in application


def test_settings_cleanup_assets_preserve_dark_neumorphism_and_are_checked() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "settings.css").read_text(encoding="utf-8").lower()
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

    assert 'href="settings.css"' in html
    assert 'src="settings_cleanup.js"' in html
    assert "box-shadow" in css
    assert "var(--surface)" in css
    assert "var(--accent)" in css
    assert "gradient(" not in css
    assert "node --check ui/web/settings_cleanup.js" in workflow
