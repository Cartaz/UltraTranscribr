from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_errors_are_stored_per_job() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")

    assert 'error: str = ""' in source
    assert "active.error = str(error or active.error)" in source
    assert 'self._finish_active("error", error)' in source
