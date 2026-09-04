from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_busy_includes_pending_and_cancelling_jobs() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")

    assert '_ACTIVE_STATUSES = {"starting", "running", "cancelling"}' in source
    assert 'job.status == "queued" or job.status in self._ACTIVE_STATUSES' in source
