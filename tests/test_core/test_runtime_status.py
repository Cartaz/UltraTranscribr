"""Behavioral tests for explicit backend runtime states."""
from pathlib import Path
from unittest.mock import MagicMock, patch

from config.settings import Settings
from core.app_controller import AppController


def _controller() -> AppController:
    with patch("core.app_controller.detect_gpu_backend", return_value="sycl"), \
         patch("core.app_controller.WhisperModelManager"), \
         patch("core.app_controller.WhisperBackend"):
        controller = AppController(Settings(vad_filter=False))
    controller._backend.is_running = False
    return controller


def test_installed_model_emits_loading_starting_ready() -> None:
    controller = _controller()
    controller._model_manager.get_model_info.return_value = {"installed": True}
    controller._model_manager.get_model_path.return_value = Path("/tmp/model.bin")
    statuses: list[str] = []
    controller.subscribe("backend_status_changed", statuses.append)

    controller.ensure_backend_started(vad=False)

    assert statuses[-3:] == ["loading_model", "starting_backend", "ready"]
    controller._backend.start.assert_called_once()


def test_missing_model_emits_download_progress_before_backend_start() -> None:
    controller = _controller()
    controller._model_manager.get_model_info.return_value = {"installed": False}
    statuses: list[str] = []
    progress: list[dict] = []
    controller.subscribe("backend_status_changed", statuses.append)
    controller.subscribe("model_download_progress", progress.append)

    def fake_download(model: str, callback):
        assert model == controller.settings.model_size
        callback(50, 100)
        return Path("/tmp/downloaded-model.bin")

    controller._model_manager.download_model.side_effect = fake_download
    controller.ensure_backend_started(vad=False)

    assert statuses[-3:] == ["downloading_model", "starting_backend", "ready"]
    assert progress[-1]["percent"] == 50
    assert progress[-1]["downloaded"] == 50
    assert progress[-1]["total"] == 100
