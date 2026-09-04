from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_batch_errors_are_non_modal_and_queue_continues() -> None:
    web = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")
    handler = web.split('if (name === "meeting_error")', 1)[1].split(
        'if (name === "meeting_review_changed")', 1
    )[0]

    assert "meetingBatchJobForSession" in handler
    assert "la coda proverà la registrazione successiva" in handler
    assert "else showError" in handler
