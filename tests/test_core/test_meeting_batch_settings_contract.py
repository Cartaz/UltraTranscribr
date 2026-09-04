from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_blocks_settings_changes_for_stable_backend_configuration() -> None:
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")
    method = application.split("def apply_settings", 1)[1].split("def refresh_devices", 1)[0]

    assert "self.meeting_batch.is_busy()" in method
    assert "coda Riunioni" in method
