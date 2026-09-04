from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_uses_independent_job_ids() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")

    assert "uuid.uuid4().hex[:12]" in source
    assert "session_id" in source
