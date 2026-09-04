from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_bridge_only_validates_serializes_and_delegates() -> None:
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    method = bridge.split("def enqueueMeetingBatch", 1)[1].split(
        "def listMeetingQueue", 1
    )[0]

    assert "json.loads(paths_json)" in method
    assert "self._application.enqueue_meeting_files(" in method
    assert "MeetingBatchCoordinator" not in bridge
    assert "MeetingManager" not in bridge
    assert "Path(path)" not in method
