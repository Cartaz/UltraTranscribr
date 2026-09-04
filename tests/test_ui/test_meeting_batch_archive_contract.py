from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_completed_batch_meetings_remain_available_in_archive() -> None:
    web = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")
    handler = web.split('if (name === "meeting_completed")', 1)[1].split(
        'if (name === "meeting_error")', 1
    )[0]

    assert "meetingRefreshList();" in handler
    assert "La coda prosegue automaticamente" in handler
