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
         patch("core.app_controller.WhisperBackend"), \
         patch("core.app_controller.PulseAudioRouter"):
        return AppController(settings=Settings())


class TestAppController:
    def test_settings_property(self, controller: AppController) -> None:
        assert controller.settings is not None
        assert isinstance(controller.settings, Settings)

    def test_buffer_property_is_aggregate_live_view(self, controller: AppController) -> None:
        assert controller.buffer is not None
        assert controller.buffer.buffer_level == 0

    def test_is_running_initially_false(self, controller: AppController) -> None:
        assert controller.is_running() is False
        assert controller.is_draining() is False
        assert controller.active_live_count() == 0

    def test_is_file_transcribing_initially_false(self, controller: AppController) -> None:
        assert controller.is_file_transcribing() is False
        assert controller.is_file_busy() is False

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

    def test_application_source_requires_selected_stream(self, controller: AppController) -> None:
        with pytest.raises(RuntimeError, match="Seleziona uno stream"):
            controller.start_live_session(audio_source="application")

    def test_start_live_session_delegates_without_stopping_existing_sessions(
        self, controller: AppController
    ) -> None:
        controller._live_sessions.create_session = MagicMock(
            side_effect=[{"id": "one"}, {"id": "two"}]
        )
        first = controller.start_live_session(
            audio_source="system", sink_name="monitor-a", language="it"
        )
        second = controller.start_live_session(
            audio_source="microphone", sink_name="mic-b", language="en"
        )
        assert first["id"] == "one"
        assert second["id"] == "two"
        assert controller._live_sessions.create_session.call_count == 2

    def test_recorded_microphone_live_scopes_setting_to_session(
        self, controller: AppController
    ) -> None:
        controller._live_sessions.create_session = MagicMock(return_value={"id": "recorded"})

        controller.start_live_session(
            audio_source="microphone",
            sink_name="mic-a",
            language="it",
            record_audio=True,
        )

        session_settings = controller._live_sessions.create_session.call_args.kwargs["settings"]
        assert session_settings.live_microphone_recording is True
        assert controller.settings.live_microphone_recording is False

    def test_record_audio_is_ignored_for_non_microphone_live(
        self, controller: AppController
    ) -> None:
        controller._live_sessions.create_session = MagicMock(return_value={"id": "system"})

        controller.start_live_session(
            audio_source="system",
            sink_name="monitor-a",
            record_audio=True,
        )

        session_settings = controller._live_sessions.create_session.call_args.kwargs["settings"]
        assert session_settings.live_microphone_recording is False

    def test_stop_live_session_is_scoped(self, controller: AppController) -> None:
        controller._live_sessions.stop_session = MagicMock(return_value=True)
        assert controller.stop_live_session("session-a", drain=True) is True
        controller._live_sessions.stop_session.assert_called_once_with(
            "session-a", drain=True
        )

    def test_list_playback_streams_delegates_to_router(self, controller: AppController) -> None:
        controller._audio_router.list_streams.return_value = []
        assert controller.list_playback_streams() == []
        controller._audio_router.list_streams.assert_called_once_with()

    def test_file_start_is_rejected_while_live_is_active(self, controller: AppController) -> None:
        controller._live_sessions.has_active_sessions = MagicMock(return_value=True)
        with pytest.raises(RuntimeError, match="sessioni Live"):
            controller.start_file_transcription("example.wav")

    def test_stop_transcription_when_idle(self, controller: AppController) -> None:
        controller.stop_transcription()

    def test_stop_file_transcription_when_idle(self, controller: AppController) -> None:
        controller.stop_file_transcription()
