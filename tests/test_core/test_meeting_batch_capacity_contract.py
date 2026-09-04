from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_has_no_artificial_small_queue_limit() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")

    assert "max_jobs" not in source
    assert "len(self._jobs) >=" not in source
