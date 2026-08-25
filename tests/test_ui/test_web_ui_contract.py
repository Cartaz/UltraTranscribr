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
        ROOT / "core" / "application_service.py",
        WEB / "index.html",
        WEB / "styles.css",
        WEB / "history.css",
        WEB / "models.css",
        WEB / "runtime.css",
        WEB / "multi_live.css",
        WEB / "app.js",
        WEB / "multi_live.js",
        WEB / "phase10.css",
        WEB / "phase10.js",
        WEB / "phase10_hardening.js",
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


def test_dark_neumorphism_uses_exact_surface_and_accent_without_gradients() -> None:
    styles = [
        (WEB / name).read_text(encoding="utf-8").lower()
        for name in ("styles.css", "history.css", "models.css", "runtime.css", "multi_live.css", "phase10.css")
    ]
    css = styles[0]
    assert "--surface: rgb(20, 20, 20)" in css
    assert "--accent: rgb(255, 102, 0)" in css
    assert "box-shadow" in css
    assert "inset" in css
    for stylesheet in styles:
        assert "gradient(" not in stylesheet


def test_frontend_is_wired_to_transport_api_and_application_workflows() -> None:
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")
    multi_script = (WEB / "multi_live.js").read_text(encoding="utf-8")
    phase10_script = (WEB / "phase10.js").read_text(encoding="utf-8")

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
        assert event in script
    assert "live_session_updated" in bridge
    assert "live_session_updated" in multi_script
    assert "meeting_updated" in bridge
    assert "meeting_updated" in phase10_script
