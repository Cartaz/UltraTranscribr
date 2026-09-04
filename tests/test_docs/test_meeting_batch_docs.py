from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_documentation_describes_real_queue_semantics() -> None:
    docs = (ROOT / "docs" / "MEETING_BATCH.md").read_text(encoding="utf-8")

    assert "FIFO sequenziale" in docs
    assert "Whisper/SYCL" in docs
    assert "Community-1/XPU" in docs
    assert "job successivo viene avviato comunque" in docs
    assert "non viene ripristinata dopo il riavvio" in docs
    assert "MeetingManager" in docs
    assert "ApplicationService" in docs
