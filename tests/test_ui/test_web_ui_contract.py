"""Static contract tests for the embedded dark-neumorphic web UI."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "ui" / "web"


def test_web_ui_files_and_native_stack_are_present() -> None:
    expected = [
        ROOT / "ui" / "__init__.py",
        ROOT / "ui" / "bridge.py",
        ROOT / "ui" / "main_window.py",
        ROOT / "ui" / "tray_icon.py",
        ROOT / "core" / "application_service.py",
        WEB / "index.html",
        WEB / "styles.css",
        WEB / "history.css",
        WEB / "models.css",
        WEB / "runtime.css",
        WEB / "multi_live.css",
        WEB / "app.js",
        WEB / "multi_live.js",
        WEB / "settings_cleanup.js",
        WEB / "file_history.js",
        WEB / "meeting.js",
    ]
    for path in expected:
        assert path.is_file(), f"missing UI file: {path.relative_to(ROOT)}"

    main_window = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "QWebEngineView" in main_window
    assert "QWebChannel" in main_window
    assert "BackendBridge" in main_window
    assert "ApplicationService" in main_window
    assert not (ROOT / "ui" / "phase10_bridge.py").exists()
    assert not (ROOT / "ui" / "multi_session_bridge.py").exists()
    assert not (ROOT / "ui" / "final_features_bridge.py").exists()


def test_dark_neumorphism_uses_exact_surface_accent_and_radius_tokens() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    linked_styles = re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', html)
    assert linked_styles
    styles = [(WEB / name).read_text(encoding="utf-8").lower() for name in linked_styles]

    css = (WEB / "styles.css").read_text(encoding="utf-8").lower()
    assert "--surface: rgb(20, 20, 20)" in css
    assert "--accent: rgb(255, 102, 0)" in css
    assert "--radius-xl: 28px" in css
    assert "--radius-lg: 22px" in css
    assert "--radius-md: 16px" in css
    assert "--radius-sm: 12px" in css
    assert "box-shadow" in css
    assert "inset" in css
    for stylesheet in styles:
        assert "gradient(" not in stylesheet


def test_frontend_is_wired_to_transport_api_and_application_workflows() -> None:
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")
    file_script = (WEB / "file_history.js").read_text(encoding="utf-8")
    live_script = (WEB / "multi_live.js").read_text(encoding="utf-8")
    meeting_script = (WEB / "meeting.js").read_text(encoding="utf-8")

    for operation in (
        "stopAllLive",
        "drainAllLive",
        "startLiveWithRecording",
        "startMeeting",
        "editMeetingSegment",
        "startFile",
        "applySettings",
    ):
        assert operation in bridge
    for operation in (
        "start_file_transcription",
        "stop_file_transcription",
        "update_settings",
        "start_live_session",
        "stop_live_session",
    ):
        assert operation in application

    for event in ("file_transcriber_progress", "file_transcriber_full_text"):
        assert event in bridge
        assert event in file_script
    assert "live_session_updated" in bridge
    assert "live_session_updated" in live_script
    assert "meeting_updated" in bridge
    assert "meeting_updated" in meeting_script
