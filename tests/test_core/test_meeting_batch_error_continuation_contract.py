from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_advances_after_terminal_history_event_not_early_completion_event() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")

    assert '("history_changed", self._on_history_changed)' in source
    assert "meeting_completed" not in source
    handler = source.split("def _on_history_changed", 1)[1].split(
        "def _finish_active", 1
    )[0]
    assert "self._maybe_start_next_async()" in handler
