"""Static contract for multi-session Live UI and WebChannel API."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "ui" / "web"


def test_multi_session_assets_are_loaded():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert (WEB / "multi_live.js").is_file()
    assert (WEB / "multi_live.css").is_file()
    assert 'href="multi_live.css"' in html
    assert 'src="multi_live.js"' in html


def test_live_launcher_remains_available_while_other_live_sessions_exist():
    script = (WEB / "multi_live.js").read_text(encoding="utf-8")
    assert "state.liveSessions = new Map()" in script
    assert 'const missingStream = state.source === "application"' in script
    assert '$("live-start").disabled = !!state.file || missingStream' in script
    assert "sessionBusy() && !active.length" not in script
    assert 'call("stopLiveSession", [session.id])' in script
    assert 'call("drainLiveSession", [session.id])' in script
    assert 'call("removeLiveSession", [session.id])' in script
    assert 'call("stopAllLive")' in script
    assert 'call("drainAllLive")' in script


def test_session_cards_show_independent_runtime_metrics():
    script = (WEB / "multi_live.js").read_text(encoding="utf-8")
    css = (WEB / "multi_live.css").read_text(encoding="utf-8").lower()
    for token in (
        "queue_wait_ms",
        "queue_peak_ms",
        "buffer_level",
        "capture_running",
        "draining",
        "session.id",
    ):
        assert token in script
    assert ".live-session-card" in css
    assert ".live-session-transcript" in css
    assert "gradient(" not in css


def test_live_module_registers_with_shared_runtime_without_global_overrides():
    script = (WEB / "multi_live.js").read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert "const liveSessionsModule =" in script
    assert "UltraUI.register(liveSessionsModule)" in script
    assert "window.UltraUI = Object.freeze" in app
    assert "function registerUIModule" in app
    assert "Legacy" not in script
    assert "refreshStreams = function" not in script
    assert "refreshDevices = function" not in script


def test_webchannel_exposes_session_scoped_operations_and_events():
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")
    controller = (ROOT / "core" / "app_controller.py").read_text(encoding="utf-8")
    manager = (ROOT / "core" / "live_sessions.py").read_text(encoding="utf-8")

    for operation in (
        "startLive",
        "stopLiveSession",
        "drainLiveSession",
        "removeLiveSession",
        "stopAllLive",
        "drainAllLive",
    ):
        assert operation in bridge
    for event in (
        "live_session_created",
        "live_session_updated",
        "live_session_buffer_level",
        "live_session_queue_wait",
        "live_session_text",
        "live_session_error",
    ):
        assert event in bridge
        assert event in manager
    assert "LiveSessionManager" in controller
    assert "start_live_session" in application
    assert "stop_live_session" in application


def test_shared_backend_is_serialized_and_reports_queue_wait():
    backend = (ROOT / "core" / "whisper_backend.py").read_text(encoding="utf-8")
    transcriber = (ROOT / "core" / "transcriber.py").read_text(encoding="utf-8")
    assert "with self._io_lock:" in backend
    assert "on_queue_wait" in backend
    assert "transcriber_queue_wait" in transcriber
