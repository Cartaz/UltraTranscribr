from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "ui" / "web" / "meeting.js"
CSS = ROOT / "ui" / "web" / "meeting.css"


def test_manual_speaker_change_updates_only_the_current_review_row() -> None:
    web = WEB.read_text(encoding="utf-8")

    handler = web.split('call("setMeetingSegmentSpeaker"', 1)[1].split(
        "speakerControls.append", 1
    )[0]
    assert "meetingApplySpeakerPresentation" in handler
    assert "meetingRenderReview();" not in handler
    assert "select.disabled = true" in web
    assert "select.disabled = false" in handler


def test_review_change_event_does_not_reload_the_open_meeting() -> None:
    web = WEB.read_text(encoding="utf-8")

    handler = web.split('if (name === "meeting_review_changed")', 1)[1].split(
        'if (name === "meeting_source_status")', 1
    )[0]
    assert "meetingLoad" not in handler
    assert "meetingRenderReview" not in handler


def test_full_review_rerenders_can_preserve_inner_list_scroll_position() -> None:
    web = WEB.read_text(encoding="utf-8")

    assert "function meetingRenderReviewPreservingListPosition()" in web
    assert '$("meeting-review-list")?.scrollTop' in web
    assert "list.scrollTop = scrollTop" in web
    assert "meetingRenderReviewPreservingListPosition();" in web


def test_meeting_review_editor_uses_page_scroll_and_compact_rows() -> None:
    css = CSS.read_text(encoding="utf-8")
    review_rule = css.split(".meeting-review-list{", 1)[1].split("}", 1)[0]
    segment_rule = css.split(".meeting-review-segment{", 1)[1].split("}", 1)[0]
    textarea_rule = css.split(".meeting-review-segment textarea{", 1)[1].split("}", 1)[0]

    assert "max-height" not in review_rule
    assert "overflow" not in review_rule
    assert "gap:10px" in review_rule
    assert "padding:12px" in segment_rule
    assert "min-height:60px" in textarea_rule


def test_meeting_archive_exposes_confirmed_per_session_deletion() -> None:
    web = WEB.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    assert "function meetingDeleteSession(item)" in web
    assert "window.confirm" in web
    assert 'call("deleteHistorySession"' in web
    assert "meetingClearReview(sessionId)" in web
    assert 'remove.textContent = "Elimina"' in web
    assert "meeting-history-entry" in web
    assert "meeting-history-delete" in web
    assert ".meeting-history-entry" in css
    assert ".meeting-history-delete" in css
