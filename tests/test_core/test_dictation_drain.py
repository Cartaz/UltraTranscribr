"""A finite backlog can outlive one request's timeout without losing its tail."""

import time

import numpy as np

from config.constants import DictationDefaults
from config.settings import Settings
from core.buffer_manager import BufferManager
from core.dictation_session import DictationService, DictationTranscriberThread


def test_release_drains_many_bounded_requests_before_emitting_final_text(monkeypatch):
    monkeypatch.setattr(DictationDefaults, "REQUEST_TIMEOUT_S", 0.3)
    events = []

    class Backend:
        calls = 0

        def transcribe_audio(self, *args, **kwargs):
            time.sleep(0.25)  # Each request completes before its own timeout.
            self.calls += 1
            return f"frase {self.calls}"

    backend = Backend()
    buffer = BufferManager()
    for _ in range(24):
        buffer.put(np.full(16000, 0.1, dtype=np.float32))
    buffer.close_input()

    def emit(name, payload):
        events.append((name, payload))

    worker = DictationTranscriberThread(buffer, backend, Settings(), event_sink=emit)
    service = DictationService(
        backend=backend, backend_initializer=lambda _: None, event_sink=emit
    )
    service._transcriber = worker
    worker.start()
    try:
        service._cleanup_worker(None, worker, buffer, preserve_error=False)
        assert not worker.is_alive()
        assert backend.calls == 24
        assert any(name == "dictation_final_text" and text for name, text in events)
        assert service.snapshot()["status"] == "idle"
    finally:
        worker.stop()
        worker.join(timeout=2)
        service.shutdown()
