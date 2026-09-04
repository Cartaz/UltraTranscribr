from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_progress_is_clamped_for_ui_serialization() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")
    helper = source.split("def _progress", 1)[1].split("def _emit_job", 1)[0]

    assert "max(0, min(100" in helper
    assert "TypeError" in helper
    assert "ValueError" in helper
