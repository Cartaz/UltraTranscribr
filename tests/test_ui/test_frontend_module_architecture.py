"""Contracts for the domain-oriented frontend module architecture."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "ui" / "web"


def _read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_domain_modules_are_loaded_without_milestone_chain() -> None:
    html = _read("index.html")
    settings = _read("settings_cleanup.js")
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

    assert 'src="app.js"' in html
    assert 'src="ui_runtime.js"' not in html
    assert 'src="multi_live.js"' in html
    assert html.index('src="app.js"') < html.index('src="multi_live.js"')
    assert 'loadStyle("file_history.css", "file-history")' in settings
    assert 'loadStyle("meeting.css", "meeting")' in settings
    assert 'loadScript("file_history.js", "file-history")' in settings
    assert 'loadScript("meeting.js", "meeting")' in settings
    assert (WEB / "file_history.css").is_file()
    assert (WEB / "meeting.css").is_file()
    assert "phase10_hardening.js" not in settings
    assert "final_features.js" not in settings
    assert "power_user.js" not in settings
    assert "power_user.css" not in settings
    assert "phase10.css" not in settings
    assert "node --check ui/web/ui_runtime.js" not in workflow
    assert "node --check ui/web/file_history.js" in workflow
    assert "node --check ui/web/meeting.js" in workflow

    for removed in (
        "ui_runtime.js",
        "power_user.js",
        "phase10.js",
        "phase10_hardening.js",
        "final_features.js",
        "power_user.css",
        "phase10.css",
    ):
        assert not (WEB / removed).exists()


def test_app_is_the_single_explicit_frontend_composition_root() -> None:
    app = _read("app.js")
    live = _read("multi_live.js")
    settings = _read("settings_cleanup.js")
    history = _read("file_history.js")
    meeting = _read("meeting.js")

    assert "const uiModules = []" in app
    assert "const uiRuntime = {bound: false, bootstrap: null}" in app
    assert "function registerUIModule" in app
    assert "function lastUIHandler" in app
    assert "window.UltraUI = Object.freeze" in app
    assert "uiRuntime.bound = true" in app
    assert "uiRuntime.bootstrap = bootstrap" in app
    assert "module.event?.(name, value, payload)" in app
    assert "module.isBusy?.() === true" in app
    assert "module.hydrate?.(moduleBootstrap)" in app

    for global_name in (
        "bind",
        "hydrate",
        "event",
        "sessionBusy",
        "liveUI",
        "fileUI",
        "sourceUI",
        "switchView",
        "refreshStreams",
        "refreshDevices",
        "showHistorySession",
        "clearHistorySelection",
        "refreshHistoryList",
    ):
        assert f"{global_name} = function" not in app

    assert "UltraUI.register(liveSessionsModule)" in live
    assert "UltraUI.register(settingsModule)" in settings
    assert "UltraUI.register(fileHistoryModule)" in history
    assert "UltraUI.register(meetingModule)" in meeting

    for source in (live, settings, history, meeting):
        assert "Legacy" not in source
        for global_name in (
            "bind",
            "hydrate",
            "event",
            "sessionBusy",
            "liveUI",
            "fileUI",
            "sourceUI",
            "switchView",
            "refreshStreams",
            "refreshDevices",
            "showHistorySession",
            "clearHistorySelection",
            "refreshHistoryList",
        ):
            assert f"{global_name} = function" not in source


def test_backend_and_history_final_features_live_in_domain_modules() -> None:
    settings = _read("settings_cleanup.js")
    history = _read("file_history.js")
    assert 'name="backend_instances"' in settings
    assert 'name="preload_model"' in settings
    assert "renameHistorySession" in history
    assert "getSessionRecordingInfo" in history
    assert "deleteSessionRecording" in history


def test_main_window_uses_single_backend_bridge_and_application_service() -> None:
    text = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "from ui.bridge import BackendBridge, BridgeLogHandler" in text
    assert "from core.application_service import ApplicationService" in text
    assert "self._bridge = BackendBridge(application, self)" in text
    assert "BackendBridge(controller" not in text
