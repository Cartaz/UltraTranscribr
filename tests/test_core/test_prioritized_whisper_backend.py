import threading
import time
import sys
import types

_stub = types.ModuleType("core.whisper_backend")
_stub.WhisperBackend = type("WhisperBackend", (), {})
sys.modules["core.whisper_backend"] = _stub

from core.inference_scheduler import InferencePriority
from core.prioritized_whisper_backend import PrioritizedWhisperBackend


class FakeBackend:
    def __init__(self):
        self.is_running = True
        self.instance_count = 1
        self.server_url = "http://127.0.0.1:1"
        self.api_endpoint = "/inference"
        self.server_vad_enabled = True
        self.holder_started = threading.Event()
        self.release_holder = threading.Event()
        self.calls = []

    def transcribe_audio(self, audio_data, **_kwargs):
        name = audio_data.decode()
        self.calls.append(name)
        if name == "holder":
            self.holder_started.set()
            self.release_holder.wait(1)
        return name


def facade_with(fake):
    obj = PrioritizedWhisperBackend.__new__(PrioritizedWhisperBackend)
    obj._backend = fake
    obj._scheduler = None
    obj._scheduler_capacity = 0
    obj._scheduler_lock = threading.RLock()
    return obj


def test_facade_prioritizes_interactive_before_queued_batch():
    fake = FakeBackend()
    backend = facade_with(fake)
    done = []

    holder = threading.Thread(
        target=lambda: backend.transcribe_audio(b"holder", priority=InferencePriority.LIVE)
    )
    holder.start()
    assert fake.holder_started.wait(1)

    batch = threading.Thread(
        target=lambda: done.append(backend.transcribe_audio(b"batch", priority="batch"))
    )
    interactive = threading.Thread(
        target=lambda: done.append(backend.transcribe_audio(b"interactive", priority="interactive"))
    )
    batch.start()
    time.sleep(0.02)
    interactive.start()
    time.sleep(0.02)
    fake.release_holder.set()
    holder.join(1); batch.join(1); interactive.join(1)

    assert fake.calls == ["holder", "interactive", "batch"]
    assert done == ["interactive", "batch"]


def test_ensure_vad_mode_does_not_disrupt_scheduler_when_mode_is_unchanged():
    fake = FakeBackend()
    fake.ensure_calls = []
    fake.ensure_vad_mode = lambda enabled, path=None: fake.ensure_calls.append((enabled, path))
    backend = facade_with(fake)
    scheduler = backend._ensure_scheduler()
    backend.ensure_vad_mode(True, object())
    assert backend._scheduler is scheduler
    assert fake.ensure_calls == []
