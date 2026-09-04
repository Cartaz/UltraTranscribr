from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_job_snapshot_exposes_only_simple_serializable_values() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")

    assert "return asdict(self)" in source
    assert "Path" not in source.split("class MeetingBatchJob", 1)[1].split("class MeetingBatchCoordinator", 1)[0]
