from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_copy_explains_fifo_and_serial_gpu_use() -> None:
    web = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")

    assert "La coda è FIFO" in web
    assert "una sola pipeline alla volta" in web
    assert "evitando inferenze GPU concorrenti" in web
