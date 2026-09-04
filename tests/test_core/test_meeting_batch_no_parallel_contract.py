from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_never_starts_next_while_manager_or_job_is_active() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")

    assert "self._active_id is not None or self._manager.is_busy()" in source
    assert 'job.status == "queued"' in source
    assert "self._manager.start_file(" in source
