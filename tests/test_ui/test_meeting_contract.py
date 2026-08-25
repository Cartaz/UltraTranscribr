"""Static contracts for the meeting frontend module."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "ui" / "web"


def test_meeting_ui_exposes_expected_controls_and_workflow() -> None:
    source = (WEB / "meeting.js").read_text(encoding="utf-8")
    for token in (
        "startMeeting",
        "finishMeeting",
        "cancelMeeting",
        "setMeetingSpeakerName",
        "editMeetingSegment",
        "currentTime = Number(item.start)",
        "Transcript raw originale",
        "Salva correzione",
        "deleteMeetingAudio",
    ):
        assert token in source


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
