import threading

import numpy as np

from config.settings import AudioSource, Settings
from core.audio_capture import AudioCaptureThread
from core.audio_capture_mic import microphone_capture_loop


class _Stream:
    def __init__(self, stop_event: threading.Event, data: np.ndarray) -> None:
        self.stop_event = stop_event
        self.data = data
        self.calls = 0

    def read(self, frames):
        del frames
        self.calls += 1
        self.stop_event.set()
        return self.data.copy(), False


class _Buffer:
    def __init__(self) -> None:
        self.chunks = []

    def put(self, chunk) -> None:
        self.chunks.append(np.asarray(chunk).copy())


def test_microphone_loop_tees_exact_normalized_samples_before_chunking() -> None:
    stop = threading.Event()
    source = np.linspace(-0.5, 0.5, 160, dtype=np.float32).reshape(-1, 1)
    stream = _Stream(stop, source)
    buffer = _Buffer()
    recorded = []

    microphone_capture_loop(
        stream=stream,
        stop_event=stop,
        lock=threading.Lock(),
        buffer=buffer,
        chunk_samples=80,
        native_sr=16000,
        needs_resample=False,
        sample_sink=lambda samples: recorded.append(samples.copy()),
    )

    assert len(recorded) == 1
    assert np.allclose(recorded[0], source[:, 0])
    assert len(buffer.chunks) == 2
    assert np.allclose(np.concatenate(buffer.chunks), recorded[0])


def test_live_microphone_recorder_is_created_only_for_opted_in_mic_session() -> None:
    base = Settings(audio_source=AudioSource.MICROPHONE.value)
    off = AudioCaptureThread(
        _Buffer(),
        base,
        "mic",
        AudioSource.MICROPHONE.value,
        session_id="off-session",
    )
    on = AudioCaptureThread(
        _Buffer(),
        base.with_(live_microphone_recording=True),
        "mic",
        AudioSource.MICROPHONE.value,
        session_id="on-session",
    )
    system = AudioCaptureThread(
        _Buffer(),
        base.with_(live_microphone_recording=True),
        "monitor",
        AudioSource.SYSTEM.value,
        session_id="system-session",
    )

    assert off._recording is None
    assert on._recording is not None
    assert system._recording is None
def test_monitor_audio_reaches_recorder_before_a_whole_whisper_chunk():
    from config.settings import Settings
    from core.audio_capture import AudioCaptureThread
    from core.buffer_manager import BufferManager

    recorded = []
    buffer = BufferManager()
    capture = AudioCaptureThread(
        buffer, Settings(chunk_ms=1000), audio_source="system",
        sample_sink=lambda samples: recorded.append(samples),
    )
    stereo = np.tile(np.array([0.2, 0.4], dtype=np.float32), (320, 1))
    try:
        capture._monitor_cb_wrapper(stereo, 320, None, 0)
        assert len(recorded) == 1
        np.testing.assert_allclose(recorded[0], np.full(320, 0.3), atol=1e-7)
        assert buffer.is_empty
    finally:
        buffer.close()
