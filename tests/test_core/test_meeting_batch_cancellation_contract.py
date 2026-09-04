from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_batch_cancel_marks_pending_without_deleting_completed_history() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")
    cancel = source.split("def cancel(", 1)[1].split("def clear_finished", 1)[0]

    assert 'if job.status == "queued"' in cancel
    assert 'job.status = "cancelled"' in cancel
    assert "delete" not in cancel.lower()
