from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_uses_owned_background_tasks_and_unsubscribes_on_close() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")

    assert 'BackgroundTaskGroup("MeetingBatch", join_timeout=10.0)' in source
    assert "self._tasks.close()" in source
    assert "self._unsubscribe(event, handler)" in source
    assert "daemon=True" not in source
