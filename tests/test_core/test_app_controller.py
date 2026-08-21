# tests/test_core/test_app_controller.py
"""Test per il controller principale dell'applicazione."""

from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from core.app_controller import AppController
from core.event_bus import EventBus
from core.exceptions import SinkNotFoundError


@pytest.fixture
def controller() -> AppController:
    with patch("core.app_controller.detect_gpu_backend", return_value="sycl"), \
         patch("core.app_controller.WhisperModelManager"), \
         patch("core.app_controller.WhisperBackend"):
        return AppController(settings=Settings())


class TestAppController:
    def test_settings_property(self, controller: AppController) -> None:
        assert controller.settings is not None
        assert isinstance(controller.settings, Settings)

    def test_buffer_property(self, controller: AppController) -> None:
        assert controller.buffer is not None

    def test_is_running_initially_false(self, controller: AppController) -> None:
        assert controller.is_running() is False

    def test_is_file_transcribing_initially_false(self, controller: AppController) -> None:
        assert controller.is_file_transcribing() is False

    def test_update_settings(self, controller: AppController) -> None:
        controller.update_settings(language="it")
        assert controller.settings.language == "it"

    def test_subscribe_delegates_to_event_bus(self, controller: AppController) -> None:
        handler = MagicMock()
        controller.subscribe("test_event", handler)
        EventBus().emit("test_event", None)
        handler.assert_called_once()

    def test_resolve_sink_with_explicit_name(self, controller: AppController) -> None:
        assert controller._resolve_sink("my_sink", "system") == "my_sink"

    def test_resolve_sink_auto_detect_system_not_found(self, controller: AppController) -> None:
        with patch("core.app_controller.find_source", return_value=None):
            with pytest.raises(SinkNotFoundError):
                controller._resolve_sink(None, "system")

    def test_resolve_sink_auto_detect_mic_not_found(self, controller: AppController) -> None:
        with patch("core.app_controller.find_source", return_value=None):
            with pytest.raises(SinkNotFoundError):
                controller._resolve_sink(None, "microphone")

    def test_stop_transcription_when_idle(self, controller: AppController) -> None:
        controller.stop_transcription()

    def test_stop_file_transcription_when_idle(self, controller: AppController) -> None:
        controller.stop_file_transcription()
