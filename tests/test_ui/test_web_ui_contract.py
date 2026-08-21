"""Static contract tests for the embedded dark-neumorphic web UI."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "ui" / "web"


def test_web_ui_files_and_native_stack_are_present() -> None:
    expected = [
        ROOT / "ui" / "__init__.py",
        ROOT / "ui" / "bridge.py",
        ROOT / "ui" / "main_window.py",
        ROOT / "ui" / "tray_icon.py",
        WEB / "index.html",
        WEB / "styles.css",
        WEB / "history.css",
        WEB / "app.js",
    ]
    for path in expected:
        assert path.is_file(), f"missing UI file: {path.relative_to(ROOT)}"

    main_window = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "QWebEngineView" in main_window
    assert "QWebChannel" in main_window


def test_dark_neumorphism_uses_exact_surface_and_accent_without_gradients() -> None:
    css = (WEB / "styles.css").read_text(encoding="utf-8").lower()
    history_css = (WEB / "history.css").read_text(encoding="utf-8").lower()
    assert "--surface: rgb(20, 20, 20)" in css
    assert "--accent: rgb(255, 102, 0)" in css
    assert "box-shadow" in css
    assert "inset" in css
    assert "gradient(" not in css
    assert "gradient(" not in history_css


def test_frontend_is_wired_to_real_backend_operations() -> None:
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")

    for operation in (
        "start_transcription",
        "stop_transcription",
        "stop_listening",
        "start_file_transcription",
        "stop_file_transcription",
        "update_settings",
    ):
        assert operation in bridge

    for event in (
        "transcriber_buffer_level",
        "transcriber_new_text",
        "file_transcriber_progress",
        "file_transcriber_full_text",
    ):
        assert event in bridge
        assert event in script

    assert "setInterval(" not in script
    assert "Math.random(" not in script


def test_navigation_and_accessibility_contract() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    for panel in ("live", "file", "history", "settings", "logs"):
        assert f'data-panel="{panel}"' in html
        assert f'data-view="{panel}"' in html

    assert 'aria-live="polite"' in html
    assert 'role="progressbar"' in html
    assert "aria-current" in script
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css


def test_compact_layout_has_no_page_scroll_or_redundant_session_settings() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    for element_id in ("live-language", "live-model", "file-language", "file-model", "title", "subtitle"):
        assert f'id="{element_id}"' not in html

    assert 'class="chip"' not in html
    assert '[hidden] { display: none !important; }' in css
    assert 'html, body { margin: 0; width: 100%; height: 100%; overflow: hidden;' in css
    assert 'const allowedModelChoices = ["large-v3", "large-v3-turbo", "medium"]' in script
    assert 'settings.language || "auto"' in script
    assert 'settings.model_size || "large-v3-turbo"' in script


def test_history_and_recovery_are_backed_by_python_persistence() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    controller = (ROOT / "core" / "app_controller.py").read_text(encoding="utf-8")
    transcriber = (ROOT / "core" / "transcriber.py").read_text(encoding="utf-8")

    assert 'id="history-list"' in html
    assert 'id="recovery-list"' in html
    assert "listHistory" in bridge and "getHistorySession" in bridge
    assert "listRecoveryAudio" in bridge
    assert "TranscriptHistoryStore" in controller
    assert "transcriber_new_text" in controller
    assert 'EventBus().emit("recovery_audio_saved"' in transcriber
    assert "refreshHistory" in script
