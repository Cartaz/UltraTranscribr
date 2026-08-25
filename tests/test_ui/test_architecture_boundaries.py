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


def test_audio_subsystem_has_one_managed_pactl_owner() -> None:
    service = _read("core/audio_discovery.py")
    routing = _read("core/audio_routing.py")
    sink_finder = _read("core/sink_finder.py")
    pactl = _read("core/pactl.py")
    controller = _read("core/app_controller.py")
    bridge = _read("ui/bridge.py")
    multi_bridge = _read("ui/multi_session_bridge.py")
    frontend = _read("ui/web/multi_live.js")

    assert "class AudioDiscoveryService" in service
    assert "stream_provider" not in service
    assert "PactlRunner" in service
    assert "PactlRunner" in routing
    assert "PactlRunner" in sink_finder
    assert "subprocess.run(" not in service
    assert "subprocess.run(" not in routing
    assert "subprocess.run(" not in sink_finder
    assert "class PactlRunner" in pactl
    assert "subprocess.Popen(" in pactl
    assert "shell=True" not in pactl
    assert "process.terminate()" in pactl
    assert "process.kill()" in pactl

    assert controller.count("self._pactl = PactlRunner()") == 1
    assert "PulseAudioRouter(pactl_runner=self._pactl)" in controller
    assert "pactl_runner=self._pactl" in controller
    assert "stream_provider=self.list_playback_streams" not in controller
    assert "self._audio_router.close()" in controller
    assert "self._audio_discovery.close()" in controller
    assert "self._pactl.close()" in controller
    assert controller.index("self._live_sessions.shutdown()") < controller.index("self._pactl.close()")

    assert "list_available_devices" not in bridge
    assert "evaluate_audio_source_health" not in multi_bridge
    assert "find_source" not in multi_bridge
    assert "list_available_devices" not in multi_bridge
    assert "self._controller.audio_discovery_snapshot()" in bridge
    assert "self._controller.request_audio_discovery(" in bridge
    assert "self._controller.request_audio_source_probe(" in multi_bridge
    assert 'name === "audio_devices_changed"' in frontend
    assert 'name === "playback_streams_changed"' in frontend
    assert 'name === "audio_source_health_changed"' in frontend


def test_webengine_is_local_only_and_external_links_leave_the_app() -> None:
    shell = _read("ui/main_window.py")
    assert "class LocalOnlyWebPage(QWebEnginePage)" in shell
    assert 'if scheme in self._EXTERNAL_SCHEMES:' in shell
    assert "QDesktopServices.openUrl(url)" in shell
    assert "LocalContentCanAccessRemoteUrls" in shell
    assert "False," in shell
    assert "def createWindow" in shell
