"""Deterministic race coverage for rapid start/stop/start and shutdown."""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from config.settings import Settings
from core.app_controller import AppController


def _controller(settings: Settings | None = None) -> AppController:
    with patch("core.app_controller.detect_gpu_backend", return_value="sycl"), \
         patch("core.app_controller.WhisperModelManager"), \
         patch("core.app_controller.WhisperBackend"), \
         patch("core.app_controller.TranscriptHistoryStore"), \
         patch("core.app_controller.PulseAudioRouter"):
        controller = AppController(settings or Settings(vad_filter=False))
    controller._history.create_session.side_effect = ["file-one", "file-two", "file-three"]
    return controller


def test_stale_file_startup_does_not_restart_backend_after_stop(monkeypatch) -> None:
    controller = _controller()
    controller._live_sessions = MagicMock()
    controller._live_sessions.has_active_sessions.return_value = False
    starts: list[tuple[int, object]] = []
    monkeypatch.setattr(
        controller,
        "_run_async",
        lambda generation, target, error_event: starts.append((generation, target)),
    )
    ensure = MagicMock()
    monkeypatch.setattr(controller, "ensure_backend_started", ensure)
    file_worker = MagicMock()
    monkeypatch.setattr("core.app_controller.FileTranscriberThread", file_worker)

    controller.start_file_transcription("first.wav")
    assert len(starts) == 1
    stale_target = starts[0][1]

    controller.stop_file_transcription()
    stale_target()

    ensure.assert_not_called()
    file_worker.assert_not_called()


def test_rapid_file_start_stop_start_only_launches_latest_generation(monkeypatch) -> None:
    controller = _controller()
    controller._live_sessions = MagicMock()
    controller._live_sessions.has_active_sessions.return_value = False
    targets = []
    monkeypatch.setattr(
        controller,
        "_run_async",
        lambda generation, target, error_event: targets.append(target),
    )
    monkeypatch.setattr(controller, "ensure_backend_started", MagicMock())

    first_worker = MagicMock()
    second_worker = MagicMock()
    factory = MagicMock(side_effect=[first_worker, second_worker])
    monkeypatch.setattr("core.app_controller.FileTranscriberThread", factory)

    controller.start_file_transcription("first.wav")
    first_target = targets[-1]
    controller.stop_file_transcription()
    controller.start_file_transcription("second.wav")
    second_target = targets[-1]

    first_target()
    second_target()

    # The stale first target is discarded before creating a worker, therefore
    # the first factory result is actually used by the latest generation.
    assert factory.call_count == 1
    assert factory.call_args.args[0] == "second.wav"
    first_worker.start.assert_called_once_with()
    second_worker.start.assert_not_called()


def test_stop_backend_waits_for_inflight_backend_start(monkeypatch) -> None:
    controller = _controller(Settings(vad_filter=False))
    controller._model_manager.get_model_info.return_value = {"installed": True}
    controller._model_manager.get_model_path.return_value = Path("/tmp/model.bin")

    entered_start = threading.Event()
    release_start = threading.Event()

    def blocking_start(model, vad):
        del model, vad
        entered_start.set()
        assert release_start.wait(2.0)

    controller._backend.start.side_effect = blocking_start
    controller._backend.is_running = False

    starter = threading.Thread(
        target=lambda: controller.ensure_backend_started(vad=False),
        daemon=True,
    )
    starter.start()
    assert entered_start.wait(1.0)

    stopper = threading.Thread(target=controller.stop_backend, daemon=True)
    stopper.start()

    # stop_backend must share the initialization lock, so it cannot stop a
    # process that is only half-started.
    assert not controller._backend.stop.wait_until_called(timeout=0.05) if hasattr(controller._backend.stop, "wait_until_called") else controller._backend.stop.call_count == 0

    release_start.set()
    starter.join(timeout=2.0)
    stopper.join(timeout=2.0)

    assert not starter.is_alive()
    assert not stopper.is_alive()
    controller._backend.stop.assert_called_once_with()
    assert controller._backend_started is False


def test_shutdown_is_idempotent_for_session_and_backend_lifecycle(monkeypatch) -> None:
    controller = _controller()
    stop_file = MagicMock()
    live_shutdown = MagicMock()
    stop_backend = MagicMock()
    monkeypatch.setattr(controller, "stop_file_transcription", stop_file)
    controller._live_sessions = MagicMock()
    controller._live_sessions.shutdown = live_shutdown
    monkeypatch.setattr(controller, "stop_backend", stop_backend)

    controller.shutdown()
    controller.shutdown()

    assert stop_file.call_count == 2
    assert live_shutdown.call_count == 2
    assert stop_backend.call_count == 2
    assert controller._history_subscriptions == []
