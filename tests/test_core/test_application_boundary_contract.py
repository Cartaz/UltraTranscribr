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
        "main.py": _read("main.py"),
        "ui/bridge.py": _read("ui/bridge.py"),
        "ui/main_window.py": _read("ui/main_window.py"),
    }

    forbidden = (
        "application.controller",
        "application.file_batch",
        "application.meeting",
        "self._application.controller",
        "self._application.file_batch",
        "self._application.meeting",
    )
    for path, source in sources.items():
        for token in forbidden:
            assert token not in source, f"{path} crosses ApplicationService via {token}"


def test_bridge_depends_on_application_service_not_app_controller() -> None:
    bridge = _read("ui/bridge.py")
    assert "ApplicationService" in bridge
    assert "AppController" not in bridge
    assert "BackendBridge(application" in _read("ui/main_window.py")


def test_composition_root_does_not_recreate_internal_shutdown_order() -> None:
    main = _read("main.py")
    window = _read("ui/main_window.py")

    assert "application.close()" in main
    assert "controller.shutdown()" not in main
    assert "self._application.close()" in window
    assert "self._controller.shutdown()" not in window


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
