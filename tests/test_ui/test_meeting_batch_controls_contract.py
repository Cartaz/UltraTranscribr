from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_controls_are_bound_to_queue_actions() -> None:
    web = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")

    assert '$("meeting-batch-clear").onclick = meetingClearFinishedBatch' in web
    assert '$("meeting-batch-cancel").onclick = meetingCancelBatch' in web
    assert 'call("cancelMeetingQueue"' in web
    assert 'call("clearFinishedMeetingQueue"' in web
