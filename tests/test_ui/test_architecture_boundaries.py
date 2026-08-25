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


def test_application_controller_owns_runtime_services_and_shutdown() -> None:
    controller = _read("core/app_controller.py")
    bridge = _read("ui/bridge.py")
    application = _read("core/application_service.py")
    shell = _read("ui/main_window.py")
    main = _read("main.py")
    assert "self._meeting = MeetingManager(_MeetingControllerView(self))" in controller
    assert "self._file_batch = FileBatchCoordinator(_FileBatchControllerView(self))" in controller
    assert "self._meeting.shutdown()" in controller
    assert "self._file_batch.close()" in controller
    assert "MeetingManager(" not in bridge
    assert "FileBatchCoordinator(" not in bridge
    assert "self.meeting = controller.meeting" in application
    assert "self.file_batch = controller.file_batch" in application
    assert "application = ApplicationService(controller)" in main
    assert "BackendBridge(controller, application, self)" in shell
    assert "closePowerUser" not in shell


def test_webchannel_bridge_is_transport_only() -> None:
    bridge = _read("ui/bridge.py")
    assert "threading" not in bridge
    assert "SessionNameStore" not in bridge
    assert "generate_history_postprocess" not in bridge
    assert "from core.session_recordings" not in bridge
    assert "backend.reconfigure" not in bridge
    assert "start_live_session(" not in bridge
    assert "start_file_transcription(" not in bridge
    assert "self._application.start_live(" in bridge
    assert "self._application.start_file(" in bridge
    assert "self._application.apply_settings(" in bridge
    assert not (ROOT / "ui" / "multi_session_bridge.py").exists()
    assert not (ROOT / "ui" / "phase10_bridge.py").exists()
    assert not (ROOT / "ui" / "final_features_bridge.py").exists()


def test_application_service_uses_public_controller_api_only() -> None:
    source = _read("core/application_service.py")
    assert "controller._" not in source
    assert "self.controller._" not in source
    assert "getattr(self.controller" not in source
    assert "self.controller.start_live_session(" in source
    assert "self.controller.is_file_busy()" in source


def test_meeting_control_waits_are_owned_by_core_not_webchannel_bridge() -> None:
    meeting = _read("core/meeting_manager.py")
    bridge = _read("ui/bridge.py")
    assert "control_thread: Optional[threading.Thread]" in meeting
    assert 'name=f"MeetingFinalize-' in meeting
    assert 'name=f"MeetingCancel-' in meeting
    assert "runtime.capture.join(timeout=8.0)" in meeting
    assert "runtime.capture.join(" not in bridge
    assert "runtime.control_thread.join(" not in bridge
    assert "transcriber.join(" not in bridge


def test_background_work_is_owned_below_webchannel() -> None:
    bridge = _read("ui/bridge.py")
    application = _read("core/application_service.py")
    assert "threading.Thread(" not in bridge
    assert "threading.Thread(" in application
    assert 'name=f"Application-{name}"' in application
    assert "self._bus.emit(error_event" in application


def test_audio_subsystem_has_one_managed_pactl_owner() -> None:
    service = _read("core/audio_discovery.py")
    routing = _read("core/audio_routing.py")
    sink_finder = _read("core/sink_finder.py")
    pactl = _read("core/pactl.py")
    controller = _read("core/app_controller.py")
    bridge = _read("ui/bridge.py")
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
    assert "evaluate_audio_source_health" not in bridge
    assert "find_source" not in bridge
    assert "self._controller.audio_discovery_snapshot()" in bridge
    assert "self._controller.request_audio_discovery(" in bridge
    assert "self._controller.request_audio_source_probe(" in bridge
    assert 'name === "audio_devices_changed"' in frontend
    assert 'name === "playback_streams_changed"' in frontend
    assert 'name === "audio_source_health_changed"' in frontend


def test_history_postprocess_and_recordings_live_below_bridge() -> None:
    bridge = _read("ui/bridge.py")
    application = _read("core/application_service.py")
    core = _read("core/history_postprocess.py")
    assert "generate_history_postprocess" not in bridge
    assert "SessionNameStore" not in bridge
    assert "from core.session_recordings" not in bridge
    assert "generate_history_postprocess" in application
    assert "SessionNameStore" in application
    assert "delete_recording" in application
    assert "process_text(" not in application
    assert "save_derived_output(" not in application
    assert "process_text(" in core
    assert "save_derived_output(" in core


def test_webengine_is_local_only_and_external_links_leave_the_app() -> None:
    shell = _read("ui/main_window.py")
    assert "class LocalOnlyWebPage(QWebEnginePage)" in shell
    assert 'if scheme in self._EXTERNAL_SCHEMES:' in shell
    assert "QDesktopServices.openUrl(url)" in shell
    assert "LocalContentCanAccessRemoteUrls" in shell
    assert "False," in shell
    assert "def createWindow" in shell
