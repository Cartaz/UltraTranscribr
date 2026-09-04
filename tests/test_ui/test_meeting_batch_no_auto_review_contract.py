from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_batch_completion_does_not_force_review_navigation() -> None:
    source = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")
    handler = source.split('if (name === "meeting_completed")', 1)[1].split(
        'if (name === "meeting_error")', 1
    )[0]

    batch_branch = handler.split("if (batchJob)", 1)[1].split("else", 1)[0]
    assert "meetingLoad" not in batch_branch
