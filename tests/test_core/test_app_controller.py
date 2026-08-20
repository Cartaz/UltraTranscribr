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
    """Crea un controller con impostazioni di default.

    Mocka detect_gpu_backend, WhisperModelManager e WhisperBackend per
    consentire l'esecuzione dei test su macchine senza GPU Intel Arc.
    """
    with patch("core.app_controller.detect_gpu_backend", return_value="sycl"), \
         patch("core.app_controller.WhisperModelManager"), \
         patch("core.app_controller.WhisperBackend"):
        return AppController(settings=Settings())


class TestAppController:
    """Test per il controller principale."""

    def test_settings_property(self, controller: AppController) -> None:
        """La proprieta settings deve restituire le impostazioni correnti."""
        assert controller.settings is not None
        assert isinstance(controller.settings, Settings)

    def test_buffer_property(self, controller: AppController) -> None:
        """La proprieta buffer deve restituire il BufferManager."""
        assert controller.buffer is not None

    def test_is_running_initially_false(self, controller: AppController) -> None:
        """is_running deve restituire False all'inizio."""
        assert controller.is_running() is False

    def test_is_file_transcribing_initially_false(self, controller: AppController) -> None:
        """is_file_transcribing deve restituire False all'inizio."""
        assert controller.is_file_transcribing() is False

    def test_update_settings(self, controller: AppController) -> None:
        """update_settings deve aggiornare le impostazioni e salvarle."""
        controller.update_settings(language="it")
        assert controller.settings.language == "it"

    def test_subscribe_delegates_to_event_bus(self, controller: AppController) -> None:
        """subscribe deve delegare all'EventBus."""
        handler = MagicMock()
        controller.subscribe("test_event", handler)
        # L'handler deve essere registrato nel bus
        bus = EventBus()
        bus.emit("test_event", None)
        handler.assert_called_once()

    def test_resolve_sink_with_explicit_name(self, controller: AppController) -> None:
        """_resolve_sink con nome esplicito deve restituire quel nome."""
        result = controller._resolve_sink("my_sink", "firefox")
        assert result == "my_sink"

    def test_resolve_sink_auto_detect_firefox_not_found(self, controller: AppController) -> None:
        """_resolve_sink con auto-detect Firefox fallito deve sollevare SinkNotFoundError."""
        with patch("core.app_controller.find_source", return_value=None):
            with pytest.raises(SinkNotFoundError):
                controller._resolve_sink(None, "firefox")

    def test_resolve_sink_auto_detect_mic_not_found(self, controller: AppController) -> None:
        """_resolve_sink con auto-detect microfono fallito deve sollevare SinkNotFoundError."""
        with patch("core.app_controller.find_source", return_value=None):
            with pytest.raises(SinkNotFoundError):
                controller._resolve_sink(None, "microphone")

    def test_stop_transcription_when_idle(self, controller: AppController) -> None:
        """stop_transcription non deve sollevare eccezioni se non attivo."""
        controller.stop_transcription()  # Non deve sollevare

    def test_stop_file_transcription_when_idle(self, controller: AppController) -> None:
        """stop_file_transcription non deve sollevare eccezioni se non attivo."""
        controller.stop_file_transcription()  # Non deve sollevare
