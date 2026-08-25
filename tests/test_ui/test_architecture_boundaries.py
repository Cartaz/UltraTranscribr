"""Regression guards for presentation/application ownership boundaries."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_file_batch_depends_on_narrow_application_contract() -> None:
    source = _read("core/file_batch.py")
    controller = _read("core/app_controller.py")
    assert "_startup_thread" not in source
    assert "_file_thread" not in source
    assert "getattr(self._controller" not in source
    assert "from core.app_controller import AppController" not in source
    assert "class FileBatchController(Protocol)" in source
    assert "class _FileBatchControllerView" in controller
    assert "FileBatchCoordinator(_FileBatchControllerView(self))" in controller


def test_meeting_manager_depends_on_narrow_application_contract() -> None:
    source = _read("core/meeting_manager.py")
    controller = _read("core/app_controller.py")
    assert "self._controller._file_busy" not in source
    assert "self._controller.is_file_busy()" in source
    assert "class MeetingController(Protocol)" in source
    assert "def __init__(self, controller: MeetingController)" in source
    assert "class _MeetingControllerView" in controller
    assert "MeetingManager(_MeetingControllerView(self))" in controller


def test_application_controller_owns_workflow_services_and_shutdown() -> None:
    controller = _read("core/app_controller.py")
    bridge = _read("ui/multi_session_bridge.py")
    shell = _read("ui/main_window.py")
    assert "self._meeting = MeetingManager(_MeetingControllerView(self))" in controller
    assert "self._file_batch = FileBatchCoordinator(_FileBatchControllerView(self))" in controller
    assert "self._meeting.shutdown()" in controller
    assert "self._file_batch.close()" in controller
    assert "MeetingManager(" not in bridge
    assert "FileBatchCoordinator(" not in bridge
    assert "self._meeting = controller.meeting" in bridge
    assert "self._file_batch = controller.file_batch" in bridge
    assert "closePowerUser" not in shell


def test_multi_session_live_bridge_uses_public_controller_api_only() -> None:
    source = _read("ui/multi_session_bridge.py")
    assert "self._controller._startup_thread" not in source
    assert "getattr(self._controller" not in source
    assert "self._controller.live_sessions" not in source
    assert "self._controller.start_live_session(" in source


def test_phase10_live_bridge_uses_public_controller_api_only() -> None:
    source = _read("ui/phase10_bridge.py")
    assert "self._controller._file_busy" not in source
    assert "self._controller._startup_thread" not in source
    assert "self._controller.live_sessions" not in source
    assert "self._controller.start_live_session(" in source
    assert "self._controller.is_file_busy()" in source


def test_meeting_control_waits_are_owned_by_core_not_webchannel_bridge() -> None:
    meeting = _read("core/meeting_manager.py")
    bridge = _read("ui/multi_session_bridge.py")
    assert "control_thread: Optional[threading.Thread]" in meeting
    assert 'name=f"MeetingFinalize-' in meeting
    assert 'name=f"MeetingCancel-' in meeting
    assert "runtime.capture.join(timeout=8.0)" in meeting
    assert ".join(" not in bridge


def test_webengine_is_local_only_and_external_links_leave_the_app() -> None:
    shell = _read("ui/main_window.py")
    assert "class LocalOnlyWebPage(QWebEnginePage)" in shell
    assert 'if scheme in self._EXTERNAL_SCHEMES:' in shell
    assert "QDesktopServices.openUrl(url)" in shell
    assert "LocalContentCanAccessRemoteUrls" in shell
    assert "False," in shell
    assert "def createWindow" in shell
