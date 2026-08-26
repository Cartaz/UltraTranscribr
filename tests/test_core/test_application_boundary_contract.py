"""Regression guards for the application boundary.

The presentation/composition layers may call ApplicationService workflows, but must
not use it as a service locator to reach AppController or owned core managers.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_presentation_does_not_cross_application_boundary() -> None:
    sources = {
        "ui/bridge.py": _read("ui/bridge.py"),
        "ui/main_window.py": _read("ui/main_window.py"),
    }

    forbidden = (
        "application.controller.",
        "application.file_batch.",
        "application.meeting.",
        "self._application.controller.",
        "self._application.file_batch.",
        "self._application.meeting.",
        "AppController",
    )
    for path, source in sources.items():
        for token in forbidden:
            assert token not in source, f"{path} crosses ApplicationService via {token}"


def test_bridge_and_native_shell_depend_on_application_service() -> None:
    bridge = _read("ui/bridge.py")
    window = _read("ui/main_window.py")
    main = _read("main.py")

    assert "ApplicationService" in bridge
    assert "AppController" not in bridge
    assert "ApplicationService" in window
    assert "AppController" not in window
    assert "BackendBridge(application" in window
    assert "MainWindow(application=application)" in main


def test_composition_root_owns_runtime_shutdown_order() -> None:
    main = _read("main.py")
    window = _read("ui/main_window.py")
    application = _read("core/application_service.py")

    assert "application.close()" in main
    assert "controller.shutdown()" in main
    assert main.index("application.close()") < main.index("controller.shutdown()")
    assert "self._application.close()" not in window
    assert "self.controller.shutdown()" not in application


def test_native_shell_uses_narrow_application_surface_for_desktop_state() -> None:
    application = _read("core/application_service.py")
    window = _read("ui/main_window.py")

    for method in ("desktop_state", "persist_window_geometry", "live_active"):
        assert f"def {method}" in application

    assert "self._application.desktop_state()" in window
    assert "self._application.persist_window_geometry(" in window
    assert "self._application.live_active()" in window
    assert "update_settings(" not in window
    assert ".settings" not in window


def test_application_service_remains_the_only_presentation_workflow_boundary() -> None:
    application = _read("core/application_service.py")
    bridge = _read("ui/bridge.py")

    # These capabilities belong below WebChannel. Their implementation may evolve,
    # but the presentation adapter must keep delegating them through ApplicationService.
    for method in (
        "bootstrap_snapshot",
        "apply_settings",
        "refresh_devices",
        "list_playback_streams",
        "probe_audio_source",
        "start_live",
        "start_file",
        "start_meeting",
        "list_history",
        "read_log_tail",
        "run_audio_diagnostics",
    ):
        assert f"def {method}" in application

    for forbidden in (
        "Path(file_path).is_file",
        "AppMeta.LOG_PATH.open",
        "controller.",
        "EventBus()",
        "threading.Thread",
    ):
        assert forbidden not in bridge
