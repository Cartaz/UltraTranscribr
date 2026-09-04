from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_queue_copy_states_error_continuation() -> None:
    source = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")

    assert "Un errore su una registrazione viene annotato" in source
    assert "le successive continuano automaticamente" in source
