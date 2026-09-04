from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_job_records_created_meeting_session_id() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")

    assert 'session_id: str = ""' in source
    assert 'current.session_id = str(snapshot.get("id") or "")' in source
