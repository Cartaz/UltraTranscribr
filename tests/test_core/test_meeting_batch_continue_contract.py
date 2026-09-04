from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_schedules_next_only_after_finishing_active_job() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")
    method = source.split("def _on_history_changed", 1)[1].split("def _finish_active", 1)[0]

    assert "self._finish_active" in method
    assert "self._maybe_start_next_async()" in method
