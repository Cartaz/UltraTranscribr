"""GPU ownership must move between Whisper and meeting worker processes."""
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config.settings import Settings
from core.app_controller import AppController
from core.event_bus import EventBus


def controller_with_loaded_whisper():
    controller = AppController.__new__(AppController)
    controller._settings = Settings(model_size="large-v3", vad_filter=False)
    controller._backend_init_lock = threading.Lock()
    controller._meeting_engine_active = threading.Event()
    controller._lock = threading.RLock()
    controller._shutdown_started = False
    controller._backend_started = True
    controller._backend_model_size = "large-v3"
    controller._bus = EventBus()
    controller._backend = MagicMock()
    controller._backend.is_running = True
    controller._backend.stop.side_effect = lambda: setattr(controller._backend, "is_running", False)
    controller._backend.start.side_effect = lambda *_: setattr(controller._backend, "is_running", True)
    controller._model_manager = MagicMock()
    controller._model_manager.get_model_info.return_value = {"installed": True}
    controller._model_manager.get_model_path.return_value = Path("ggml-large-v3.bin")
    return controller


@pytest.mark.parametrize("outcome", ["completed", "cancelled", "error"])
def test_switch_releases_whisper_and_loads_it_again_after_meeting(outcome):
    controller = controller_with_loaded_whisper()
    try:
        with controller.meeting_engine_session():
            controller._backend.stop.assert_called_once()
            assert not controller._backend.is_running
            assert not controller._backend_started
            assert controller._backend_model_size is None
            with pytest.raises(RuntimeError, match="fine della riunione"):
                controller.ensure_backend_started()
            controller._backend.start.assert_not_called()
            if outcome != "completed":
                raise ValueError(outcome)
    except ValueError:
        assert outcome != "completed"
    assert not controller._meeting_engine_active.is_set()
    controller.ensure_backend_started()
    controller._backend.start.assert_called_once_with(Path("ggml-large-v3.bin"), None)
    assert controller._backend_started
    assert controller._backend_model_size == "large-v3"


def test_meeting_cannot_start_if_whisper_refuses_to_unload():
    controller = controller_with_loaded_whisper()
    controller._backend.stop.side_effect = RuntimeError("Whisper ancora attivo")
    with pytest.raises(RuntimeError, match="Whisper ancora attivo"):
        with controller.meeting_engine_session():
            pytest.fail("Qwen must not load before Whisper has exited")
    controller._backend.start.assert_not_called()


def test_preload_and_meeting_switch_share_the_same_lock():
    controller = controller_with_loaded_whisper()
    entered = threading.Event()
    finished = threading.Event()

    def meeting():
        with controller.meeting_engine_session():
            entered.set()
        finished.set()

    with controller._backend_init_lock:
        thread = threading.Thread(target=meeting)
        thread.start()
        assert not entered.wait(.05)
        controller._backend.stop.assert_not_called()
    assert finished.wait(2)
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert entered.is_set()


def test_surviving_meeting_process_keeps_whisper_blocked():
    from core.meeting_engine import MeetingEngineStillRunning

    controller = controller_with_loaded_whisper()
    with pytest.raises(MeetingEngineStillRunning):
        with controller.meeting_engine_session():
            raise MeetingEngineStillRunning("worker survived shutdown")
    assert controller._meeting_engine_active.is_set()
    with pytest.raises(RuntimeError, match="fine della riunione"):
        controller.ensure_backend_started()
    controller._backend.start.assert_not_called()
