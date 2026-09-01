"""Contracts for the domain-oriented Meeting presentation module."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "ui" / "web"


def test_meeting_module_is_registered_and_ci_checked() -> None:
    source = (WEB / "meeting.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    settings = (WEB / "settings_cleanup.js").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "UltraUI.register(meetingModule)" in source
    assert 'src="meeting.js"' in html
    assert 'href="meeting.css"' in html
    assert "meeting.js" not in settings
    assert "node --check ui/web/meeting.js" in workflow
    assert "Legacy" not in source


def test_live_microphone_recording_is_opt_in_and_application_owned() -> None:
    source = (WEB / "meeting.js").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")
    settings = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
    assert 'id="live-recording" type="checkbox"' in source
    assert 'row.hidden = state.source !== "microphone"' in source
    assert "startLiveWithRecording" in source
    assert "live_microphone_recording: bool = False" in settings
    assert "self._application.start_live(" in bridge
    assert "record_audio and source == AudioSource.MICROPHONE.value" in application
    assert "record_audio=bool(" in application
    assert "self.controller.start_live_session(" in application


def test_meeting_supports_realtime_multisource_file_and_review() -> None:
    source = (WEB / "meeting.js").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    for token in (
        'button.textContent = "Riunione"',
        "startMeetingRealtime",
        "startMeetingFile",
        "finishMeeting",
        "getMeetingAudioUrl",
        "setMeetingSpeakerName",
        "editMeetingSegment",
        "currentTime = Number(item.start)",
        "Transcript raw originale",
        "Salva correzione",
        "deleteMeetingAudio",
        'meetingMode = "realtime"',
        'source: "microphone"',
        '["system", "Audio di sistema"]',
        '["application", "Applicazione"]',
        "meetingSources.length >= 8",
        "meeting-review-sources",
    ):
        assert token in source
    assert "def startMeetingRealtime" in bridge
    assert "def startMeetingFile" in bridge
    assert "len(decoded) > 8" in bridge


def test_meeting_list_uses_text_content_for_persisted_data() -> None:
    source = (WEB / "meeting.js").read_text(encoding="utf-8")
    assert "preview.textContent = item.text_preview" in source
    assert "meta.textContent =" in source
    assert "button.innerHTML" not in source


def test_meeting_busy_state_extends_shared_session_policy_without_wrapping() -> None:
    source = (WEB / "meeting.js").read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert "isBusy: meetingIsBusy" in source
    assert "uiModules.some(module => module.isBusy?.() === true)" in app
    assert "sessionBusy = function" not in source
    assert "Legacy" not in source
