from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_job_keeps_enqueue_language() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")

    assert "language: str" in source
    assert "language=str(language)" in source
