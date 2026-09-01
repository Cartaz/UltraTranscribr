"""Regression guard for the canonical Meeting entrypoints."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_legacy_single_microphone_meeting_entrypoint_is_absent() -> None:
    manager = (ROOT / "core" / "meeting_manager.py").read_text(encoding="utf-8")
    store = (ROOT / "core" / "meeting_store.py").read_text(encoding="utf-8")
    service = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")

    assert "Backward-compatible single-microphone Meeting" not in manager
    assert "Backward-compatible single-microphone Meeting" not in service
    assert "Backward-compatible single-microphone Meeting" not in bridge
    assert '"microphone": microphone' not in manager
    assert "microphone: str =" not in store
    assert "def startMeeting(" not in bridge
    assert "def start_meeting(" not in service
