"""A finite backlog can outlive one request's timeout without losing its tail."""

import threading
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

    def speak():
        # Each burst arrives after the previous request finished, so every
        # burst needs its own request whatever the thread scheduling.
        for burst in range(6):
            for _ in range(4):
                buffer.put(np.full(16000, 0.1, dtype=np.float32))
            deadline = time.monotonic() + 5
            while backend.calls <= burst and time.monotonic() < deadline:
                time.sleep(0.01)
        buffer.close_input()

    producer = threading.Thread(target=speak)
    producer.start()

    def emit(name, payload):
        events.append((name, payload))

    worker = DictationTranscriberThread(buffer, backend, Settings(), event_sink=emit)
    service = DictationService(
        backend=backend, backend_initializer=lambda _: None, event_sink=emit
    )
    service._transcriber = worker
    worker.start()
    try:
        producer.join()
        service._cleanup_worker(None, worker, buffer, preserve_error=False)
        assert not worker.is_alive()
        # Several requests ran and together outlasted one request timeout.
        assert backend.calls >= 6
        assert backend.calls * 0.25 > DictationDefaults.REQUEST_TIMEOUT_S
        assert any(name == "dictation_final_text" and text for name, text in events)
        assert service.snapshot()["status"] == "idle"
    finally:
        worker.stop()
        worker.join(timeout=2)
        service.shutdown()


def _run_transcriber(chunks, backend):
    events = []
    buffer = BufferManager()
    for chunk in chunks:
        buffer.put(chunk)
    buffer.close_input()
    worker = DictationTranscriberThread(
        buffer, backend, Settings(), event_sink=lambda n, p: events.append((n, p))
    )
    worker.start()
    worker.join(timeout=10)
    assert not worker.is_alive()
    return next(p for n, p in events if n == "dictation_final_text")


def test_backlog_queued_during_a_request_is_covered_by_one_catch_up_request():
    class Backend:
        seconds = []

        def transcribe_audio(self, wav, *args, **kwargs):
            self.seconds.append((len(wav) - 44) / 2 / 16000)
            return "ciao"

    backend = Backend()
    _run_transcriber([np.full(4000, 0.1, dtype=np.float32)] * 40, backend)
    # 10 s were queued: one request covers them instead of one per 750 ms.
    assert backend.seconds == [10.0]


def test_long_dictation_is_cut_at_a_segment_boundary_without_losing_or_repeating_words():
    rate = 16000
    words = [f"w{i}" for i in range(1, 41)]  # 40 words of 1 s each.
    gap = np.zeros(int(rate * 0.2), dtype=np.float32)

    class Backend:
        lengths = []

        def transcribe_audio(self, wav, *args, **kwargs):
            audio = np.frombuffer(wav[44:], dtype="<i2").astype(np.float32) / 32767.0
            self.lengths.append(audio.size / rate)
            loud = np.abs(audio) > 0.02
            edges = np.flatnonzero(np.diff(np.r_[0, loud.astype(np.int8), 0]))
            segments = []
            for start, end in zip(edges[::2], edges[1::2]):
                if end - start >= rate // 2:  # a cut word is unintelligible
                    level = float(np.median(np.abs(audio[start:end])))
                    segments.append(
                        {"start": start / rate, "end": end / rate, "text": f"w{round((level - 0.05) / 0.01)}"}
                    )
            return {"text": " ".join(s["text"] for s in segments), "segments": segments}

    backend = Backend()
    buffer = BufferManager()
    events = []
    worker = DictationTranscriberThread(
        buffer, backend, Settings(), event_sink=lambda n, p: events.append((n, p))
    )
    worker.start()
    for i in range(1, 41):
        buffer.put(np.full(rate, 0.05 + 0.01 * i, dtype=np.float32))
        buffer.put(gap)
        time.sleep(0.02)
    buffer.close_input()
    worker.join(timeout=20)
    assert not worker.is_alive()
    final = next(p for n, p in events if n == "dictation_final_text")
    assert final.split() == words
    typed = " ".join(p for n, p in events if n == "dictation_text_committed").split()
    assert typed == words
    # The window was restarted instead of growing past Whisper's 30 s.
    assert max(backend.lengths) < 30


def test_short_phrase_after_a_long_pause_is_not_averaged_into_silence():
    class Backend:
        seconds = []

        def transcribe_audio(self, wav, *args, **kwargs):
            self.seconds.append((len(wav) - 44) / 2 / 16000)
            return "ok invia"

    silence = [np.zeros(4000, dtype=np.float32)] * 72  # 18 s
    phrase = [np.full(4000, 0.015, dtype=np.float32)] * 4  # 1 s
    backend = Backend()
    buffer = BufferManager()
    events = []
    worker = DictationTranscriberThread(
        buffer, backend, Settings(), event_sink=lambda n, p: events.append((n, p))
    )
    worker.start()
    for chunk in silence:
        buffer.put(chunk)
        time.sleep(0.002)
    for chunk in phrase:
        buffer.put(chunk)
    buffer.close_input()
    worker.join(timeout=10)
    assert next(p for n, p in events if n == "dictation_final_text") == "ok invia"
    assert max(backend.seconds) < 18


def test_stop_interrupts_a_backlog_without_publishing_more_text():
    class Backend:
        calls = 0

        def transcribe_audio(self, *args, **kwargs):
            self.calls += 1
            worker.stop()
            return "testo"

    backend = Backend()
    buffer = BufferManager()
    for _ in range(120):  # 120 s: several segments of backlog
        buffer.put(np.full(16000, 0.1, dtype=np.float32))
    events = []
    worker = DictationTranscriberThread(
        buffer, backend, Settings(), event_sink=lambda n, p: events.append((n, p))
    )
    worker.start()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert backend.calls == 1
    assert not [n for n, _p in events if n == "dictation_text_committed"]


def test_continuous_speech_is_not_cut_mid_word_before_the_hard_cap():
    class Backend:
        seconds = []

        def transcribe_audio(self, wav, *args, **kwargs):
            self.seconds.append((len(wav) - 44) / 2 / 16000)
            return "parola"

    backend = Backend()
    _run_transcriber([np.full(16000, 0.1, dtype=np.float32)] * 27, backend)
    # 27 s without a pause: past WINDOW_MS but under the hard cap, so the
    # window is transcribed whole instead of being cut inside a word.
    assert backend.seconds == [27.0]


def test_speech_onset_after_silence_is_kept():
    class Backend:
        seconds = []

        def transcribe_audio(self, wav, *args, **kwargs):
            self.seconds.append((len(wav) - 44) / 2 / 16000)
            return "ciao"

    backend = Backend()
    buffer = BufferManager()
    events = []
    worker = DictationTranscriberThread(
        buffer, backend, Settings(), event_sink=lambda n, p: events.append((n, p))
    )
    worker.start()
    for _ in range(12):  # 3 s of silence, seen by several silent checks
        buffer.put(np.zeros(4000, dtype=np.float32))
        time.sleep(0.01)
    for _ in range(8):  # 2 s of speech
        buffer.put(np.full(4000, 0.1, dtype=np.float32))
    buffer.close_input()
    worker.join(timeout=10)
    assert backend.seconds and 2.0 <= backend.seconds[-1] < 3.0
