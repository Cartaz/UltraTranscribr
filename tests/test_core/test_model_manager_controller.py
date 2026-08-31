"""Controller tests for managed model operations."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from core.app_controller import AppController
from core.event_bus import EventBus


@pytest.fixture
def controller() -> AppController:
    with patch("core.app_controller.detect_gpu_backend", return_value="sycl"), \
         patch("core.app_controller.WhisperModelManager"), \
         patch("core.app_controller.PrioritizedWhisperBackend"):
        instance = AppController(settings=Settings())
    manager = MagicMock()
    manager.ui_model_choices.return_value = ("large-v3", "large-v3-turbo", "medium")
    instance._model_manager = manager
    return instance


def test_list_models_delegates_to_model_manager(controller: AppController) -> None:
    expected = [{"model": "medium", "installed": False}]
    controller._model_manager.list_ui_models.return_value = expected
    assert controller.list_models() == expected


def test_download_model_emits_real_progress_events(controller: AppController) -> None:
    events: list[tuple[str, object]] = []
    bus = EventBus()
    for event_name in ("model_download_started", "model_download_progress", "model_status_changed"):
        bus.subscribe(event_name, lambda payload, name=event_name: events.append((name, payload)))

    def fake_download(model: str, progress) -> Path:
        assert model == "medium"
        progress(50, 100)
        progress(100, 100)
        return Path("/tmp/ggml-medium.bin")

    controller._model_manager.download_model.side_effect = fake_download

    result = controller.download_model("medium")

    assert result == "/tmp/ggml-medium.bin"
    assert events[0] == ("model_download_started", {"model": "medium"})
    progress_payloads = [payload for name, payload in events if name == "model_download_progress"]
    assert progress_payloads[0]["percent"] == 50
    assert progress_payloads[-1]["percent"] == 100
    assert events[-1][0] == "model_status_changed"


def test_model_operations_are_rejected_while_transcribing(controller: AppController) -> None:
    with patch.object(controller._live_sessions, "has_active_sessions", return_value=True):
        with pytest.raises(RuntimeError):
            controller.download_model("medium")
        with pytest.raises(RuntimeError):
            controller.delete_model("medium")


def test_delete_model_stops_idle_backend_before_removal(controller: AppController) -> None:
    controller._backend.is_running = True
    controller._model_manager.delete_model.return_value = True

    assert controller.delete_model("medium") is True

    controller._backend.stop.assert_called_once()
    controller._model_manager.delete_model.assert_called_once_with("medium")


def test_unknown_ui_model_is_rejected(controller: AppController) -> None:
    with pytest.raises(ValueError):
        controller.download_model("tiny")
    with pytest.raises(ValueError):
        controller.delete_model("tiny")
