"""Regression guards for presentation/application ownership boundaries."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_file_batch_does_not_inspect_controller_worker_threads() -> None:
    source = _read("core/file_batch.py")
    assert "_startup_thread" not in source
    assert "_file_thread" not in source
    assert "getattr(self._controller" not in source
    assert "self._controller.is_file_transcribing()" in source


def test_meeting_manager_uses_public_file_lifecycle_state() -> None:
    source = _read("core/meeting_manager.py")
    assert "self._controller._file_busy" not in source
    assert "self._controller.is_file_busy()" in source


def test_phase10_live_bridge_uses_public_controller_api_only() -> None:
    source = _read("ui/phase10_bridge.py")
    assert "self._controller._file_busy" not in source
    assert "self._controller._startup_thread" not in source
    assert "self._controller.live_sessions" not in source
    assert "self._controller.start_live_session(" in source
    assert "self._controller.is_file_busy()" in source
