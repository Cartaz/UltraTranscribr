from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_phase10_frontend_modules_are_loaded_and_ci_checked() -> None:
    settings = (ROOT / "ui" / "web" / "settings_cleanup.js").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert 'phase6InjectScript("phase10.js"' in settings
    assert 'phase6InjectScript("phase10_hardening.js"' in settings
    assert "script.async = false" in settings
    assert "node --check ui/web/phase10.js" in workflow
    assert "node --check ui/web/phase10_hardening.js" in workflow


def test_live_microphone_recording_is_opt_in_and_controller_owned() -> None:
    source = (ROOT / "ui" / "web" / "phase10.js").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "phase10_bridge.py").read_text(encoding="utf-8")
    controller = (ROOT / "core" / "app_controller.py").read_text(encoding="utf-8")
    settings = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
    assert 'id="live-recording" type="checkbox"' in source
    assert 'row.hidden = state.source !== "microphone"' in source
    assert "startLiveWithRecording" in source
    assert "live_microphone_recording: bool = False" in settings
    assert "should_record = bool(record_audio and source == AudioSource.MICROPHONE.value)" in bridge
    assert "self._controller.start_live_session(" in bridge
    assert "record_audio=should_record" in bridge
    assert "self._controller.live_sessions.create_session" not in bridge
    assert "live_microphone_recording=bool(" in controller


def test_meeting_tab_always_records_and_supports_review() -> None:
    source = (ROOT / "ui" / "web" / "phase10.js").read_text(encoding="utf-8")
    for token in (
        'button.textContent = "Riunione"',
        "startMeeting",
        "finishMeeting",
        "getMeetingAudioUrl",
        "setMeetingSpeakerName",
        "editMeetingSegment",
        "currentTime = Number(item.start)",
        "Transcript raw originale",
        "Salva correzione",
        "deleteMeetingAudio",
    ):
        assert token in source


def test_meeting_list_uses_text_content_for_persisted_transcript_data() -> None:
    source = (ROOT / "ui" / "web" / "phase10_hardening.js").read_text(encoding="utf-8")
    assert "preview.textContent = item.text_preview" in source
    assert "meta.textContent =" in source
    assert "button.innerHTML" not in source


def test_live_recording_can_be_reopened_and_deleted_from_history() -> None:
    source = (ROOT / "ui" / "web" / "phase10_hardening.js").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "phase10_bridge.py").read_text(encoding="utf-8")
    assert "getSessionRecordingInfo" in source
    assert "deleteSessionRecording" in source
    assert "def getSessionRecordingInfo" in bridge
    assert "def deleteSessionRecording" in bridge
    assert "la trascrizione è stata conservata" in source


def test_desktop_shell_uses_phase10_bridge() -> None:
    source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "from ui.phase10_bridge import Phase10BackendBridge" in source
    assert "self._bridge = Phase10BackendBridge(controller, self)" in source
