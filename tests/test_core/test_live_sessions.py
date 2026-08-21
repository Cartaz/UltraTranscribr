"""Deterministic tests for independent Live session runtime state."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from config.settings import Settings
from core.live_sessions import LiveSessionManager


class _ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, **_ignored):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        self._alive = False

    def start(self):
        self._alive = True
        if self._target is not None:
            self._target(*self._args, **self._kwargs)
        self._alive = False

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        del timeout
        self._alive = False


class _FakeCapture:
    instances = []

    def __init__(self, *args, **kwargs):
        del args, kwargs
        self.alive = False
        self.stopped = False
        type(self).instances.append(self)

    def start(self):
        self.alive = True

    def stop(self):
        self.stopped = True
        self.alive = False

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        del timeout
        self.alive = False


class _FakeTranscriber(_FakeCapture):
    instances = []


def _manager():
    history = MagicMock()
    history.create_session.side_effect = ["live-one", "live-two", "live-three"]
    history.get_session.return_value = {"text": ""}
    router = MagicMock()
    backend = MagicMock()
    initializer = MagicMock()
    manager = LiveSessionManager(
        backend=backend,
        router=router,
        history=history,
        backend_initializer=initializer,
        sink_resolver=lambda sink, source: sink or f"{source}-auto",
    )
    return manager, history, initializer


def test_two_live_sessions_keep_independent_workers_and_buffers():
    _FakeCapture.instances.clear()
    _FakeTranscriber.instances.clear()
    manager, history, initializer = _manager()

    with patch("core.live_sessions.threading.Thread", _ImmediateThread), \
         patch("core.live_sessions.AudioCaptureThread", _FakeCapture), \
         patch("core.live_sessions.TranscriberThread", _FakeTranscriber):
        first = manager.create_session(
            settings=Settings(), audio_source="system", sink_name="monitor-a"
        )
        second = manager.create_session(
            settings=Settings(), audio_source="microphone", sink_name="mic-b"
        )

        assert first["id"] == "live-one"
        assert second["id"] == "live-two"
        assert manager.active_count() == 2
        assert manager._sessions["live-one"].buffer is not manager._sessions["live-two"].buffer
        assert initializer.call_count == 2
        assert len(_FakeCapture.instances) == 2
        assert len(_FakeTranscriber.instances) == 2

        manager.stop_session("live-one", drain=False)
        assert manager.get_session("live-one")["terminal"] is True
        assert manager.get_session("live-two")["terminal"] is False
        assert _FakeCapture.instances[0].stopped is True
        assert _FakeCapture.instances[1].stopped is False
        assert history.set_status.called


def test_drain_closes_only_selected_input_and_keeps_transcriber_alive():
    _FakeCapture.instances.clear()
    _FakeTranscriber.instances.clear()
    manager, _history, _initializer = _manager()

    with patch("core.live_sessions.threading.Thread", _ImmediateThread), \
         patch("core.live_sessions.AudioCaptureThread", _FakeCapture), \
         patch("core.live_sessions.TranscriberThread", _FakeTranscriber):
        manager.create_session(
            settings=Settings(), audio_source="system", sink_name="monitor-a"
        )
        manager.create_session(
            settings=Settings(), audio_source="microphone", sink_name="mic-b"
        )

        manager.stop_session("live-one", drain=True)
        first = manager._sessions["live-one"]
        second = manager._sessions["live-two"]
        assert first.status == "draining"
        assert first.terminal is False
        assert first.buffer.input_closed is True
        assert first.transcriber.is_alive() is True
        assert second.buffer.input_closed is False
        assert second.capture.is_alive() is True


def test_queue_metrics_and_text_are_scoped_to_session():
    manager, history, _initializer = _manager()
    session = MagicMock()
    session.id = "manual"
    session.queue_wait_ms = 0.0
    session.queue_peak_ms = 0.0
    session.queue_samples = 0
    session.terminal = False

    manager._worker_event(session, "transcriber_queue_wait", 42.5)
    manager._worker_event(session, "transcriber_queue_wait", 12.0)
    manager._worker_event(session, "transcriber_new_text", "hello world")

    assert session.queue_wait_ms == 12.0
    assert session.queue_peak_ms == 42.5
    assert session.queue_samples == 2
    history.append_text.assert_called_once_with("manual", "hello world")
