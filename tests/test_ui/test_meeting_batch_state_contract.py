from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_busy_state_participates_in_shared_ui_policy() -> None:
    source = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")

    assert "return meetingRuntimeIsBusy() || meetingBatchIsBusy();" in source
    assert "isBusy: meetingIsBusy" in source
