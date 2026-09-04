from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_clear_finished_keeps_queued_and_active_jobs() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")
    method = source.split("def clear_finished", 1)[1].split("def close", 1)[0]

    assert 'job.status == "queued"' in method
    assert "job.status in self._ACTIVE_STATUSES" in method
