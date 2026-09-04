from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_manual_speaker_assignment_crosses_all_application_layers() -> None:
    manager = (ROOT / "core" / "meeting_manager.py").read_text(encoding="utf-8")
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    web = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")

    assert "def set_segment_speaker" in manager
    assert "self.store.set_review_speaker_override" in manager
    assert "def set_meeting_segment_speaker" in application
    assert "self.meeting.set_segment_speaker" in application
    assert "def setMeetingSegmentSpeaker" in bridge
    assert "self._application.set_meeting_segment_speaker" in bridge
    assert 'call("setMeetingSegmentSpeaker"' in web


def test_review_exposes_automatic_manual_and_overlap_states_without_html_injection() -> None:
    web = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")

    assert "meeting-speaker-select" in web
    assert "speaker_override" in web
    assert "Automatico ·" in web
    assert "Speaker ? · incerto" in web
    assert "Parlato sovrapposto rilevato" in web
    assert "speaker_diarization_segments" in web
    assert "meetingKnownSpeakerIds" in web
    assert "status.textContent" in web
    assert "overlap.textContent" in web


def test_review_help_describes_word_level_behavior_and_legacy_fallback() -> None:
    web = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")

    assert "timestamp parola-per-parola" in web
    assert "Le riunioni più vecchie restano modificabili manualmente" in web
