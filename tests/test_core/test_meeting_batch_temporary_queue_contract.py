from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_does_not_add_queue_persistence_or_settings_state() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")

    assert "Settings" not in source
    assert "json.dump" not in source
    assert "write_text" not in source
