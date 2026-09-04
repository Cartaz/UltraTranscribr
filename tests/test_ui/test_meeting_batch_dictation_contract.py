from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_application_boundary_blocks_dictation_while_meeting_batch_is_active() -> None:
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")
    method = application.split("def dictation_shortcut_pressed", 1)[1].split(
        "def dictation_shortcut_released", 1
    )[0]

    assert "self.meeting_batch.is_busy()" in method
    assert 'self._bus.emit("dictation_error"' in method
    assert "self.controller.dictation_shortcut_pressed()" in method
