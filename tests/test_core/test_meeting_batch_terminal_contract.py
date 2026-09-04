from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_terminal_phases_match_meeting_runtime_contract() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")

    assert '_TERMINAL_PHASES = {"completed", "error", "cancelled", "interrupted"}' in source
