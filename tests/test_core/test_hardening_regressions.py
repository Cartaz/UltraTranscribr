"""Regression tests for bugs found by the August 2026 audit."""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import numpy as np

from config.constants import ProcessDefaults, SYCLDefaults
from config.settings import Settings
from core.audio_capture import AudioCaptureThread
from core.audio_resampler import StreamingLinearResampler
from core.buffer_manager import BufferManager
from core.file_transcriber import FileTranscriberThread
from core.text_dedup import deduplicate_text
from core.whisper_backend import WhisperBackend


def test_long_file_timeout_is_per_chunk_not_83_hours():
    assert SYCLDefaults.FILE_CHUNK_REQUEST_TIMEOUT_S == 600.0
    assert SYCLDefaults.LIVE_REQUEST_TIMEOUT_S == 180.0
    assert ProcessDefaults.FILE_SEGMENT_LENGTH_S == 30.0


def test_real_greetings_are_preserved():
    assert deduplicate_text("Buongiorno") == "Buongiorno"
    assert deduplicate_text("Thank you") == "Thank you"


def test_music_preserves_repetitions():
    text = "we are here we are here we are here"
    assert deduplicate_text(text, preserve_repetitions=True) == text


def test_buffer_spill_is_fifo_and_stats_reset():
    b = BufferManager(warn_threshold=2, max_memory_chunks=2)
    chunks = [np.full(8, i, dtype=np.float32) for i in range(7)]
    for chunk in chunks:
        b.put(chunk)
    got = [b.get_nowait() for _ in chunks]
    for expected, actual in zip(chunks, got):
        np.testing.assert_array_equal(actual, expected)
    b.put(chunks[0])
    b.clear()
    assert b.total_put == 0 and b.total_get == 0 and b.qsize == 0
    b.close()


def test_streaming_resampler_has_no_large_accumulating_drift():
    r = StreamingLinearResampler(48000, 16000)
    total = 0
    remaining = 48000 * 60
    while remaining:
        n = min(1024, remaining)
        total += len(r.process(np.zeros(n, dtype=np.float32)))
        remaining -= n
    total += len(r.flush())
    assert abs(total - 16000 * 60) <= 2


def test_microphone_uses_native_default_sample_rate(monkeypatch):
    import core.audio_resampler as ar

    monkeypatch.setattr(
        ar.sd,
        "query_devices",
        lambda device: {
            "name": "default",
            "default_samplerate": 48000.0,
            "max_input_channels": 2,
        },
    )

    def unexpected_check(*args, **kwargs):
        raise AssertionError("16 kHz must not be probed/forced via PortAudio")

    monkeypatch.setattr(
        ar.sd,
        "check_input_settings",
        unexpected_check,
        raising=False,
    )
    assert ar.query_device_sample_rate("default") == 48000


def test_audio_stop_only_signals_worker_thread():
    buffer = BufferManager(warn_threshold=2, max_memory_chunks=2)
    worker = AudioCaptureThread(
        buffer,
        Settings(),
        device_name="default",
        audio_source="microphone",
    )
    fake_stream = MagicMock()
    worker._stream = fake_stream

    worker.stop()

    assert worker._stop_event.is_set()
    fake_stream.stop.assert_not_called()
    fake_stream.close.assert_not_called()
    buffer.close()


def test_capture_reconnect_streak_reaches_limit(monkeypatch):
    buffer = BufferManager(warn_threshold=2, max_memory_chunks=2)
    worker = AudioCaptureThread(
        buffer,
        Settings(),
        device_name="default",
        audio_source="microphone",
    )
    worker._max_reconnect_attempts = 3
    worker._reconnect_delay = 0.0
    open_stream = MagicMock()
    capture_loop = MagicMock(side_effect=RuntimeError("boom"))
    close_stream = MagicMock()
    monkeypatch.setattr(worker, "_open_stream", open_stream)
    monkeypatch.setattr(worker, "_capture_loop", capture_loop)
    monkeypatch.setattr(worker, "_close_stream", close_stream)

    worker.run()

    assert open_stream.call_count == 3
    assert capture_loop.call_count == 3
    assert buffer.input_closed
    buffer.close()


def test_backend_vad_command_requires_model(tmp_path):
    settings = Settings()
    b = WhisperBackend(settings, tmp_path)
    b._server_binary = "/bin/true"
    b._vad_model_path = tmp_path / "vad.bin"
    cmd = b._build_cmd(tmp_path / "model.bin", True)
    assert "--vad-model" in cmd
    assert "--vad-min-silence-duration-ms" in cmd
    assert str(settings.beam_size) in cmd


def test_endpoint_order_prefers_documented_inference():
    import core.whisper_backend as wb

    assert wb._ENDPOINTS[0] == "/inference"


def test_multipart_does_not_send_undocumented_vad_field(tmp_path):
    b = WhisperBackend(Settings(), tmp_path)
    body = b._build_multipart(b"wav", "it", "BOUNDARY")
    assert b'name="vad"' not in body


def test_file_thread_uses_explicit_ui_language():
    worker = FileTranscriberThread(
        "audio.wav",
        MagicMock(),
        Settings(language="en"),
        language="it",
    )
    assert worker._language == "it"


def test_demucs_output_is_the_file_actually_transcribed(monkeypatch):
    worker = FileTranscriberThread(
        "song.mp3",
        MagicMock(),
        Settings(),
        song_mode=True,
        isolate_vocals_flag=True,
    )
    seen = {}
    monkeypatch.setattr(
        worker,
        "_run_vocal_isolation",
        lambda: "/tmp/vocals.wav",
    )
    monkeypatch.setattr(
        worker,
        "_transcribe_progressively",
        lambda source, start: seen.update(source=source),
    )
    monkeypatch.setattr(worker, "_cleanup", lambda: None)
    worker.run()
    assert seen["source"] == "/tmp/vocals.wav"


def test_demucs_device_selection_is_owned_by_shared_xpu_runtime(monkeypatch, tmp_path):
    import core.vocal_isolator as vi

    input_file = tmp_path / "song.wav"
    input_file.write_bytes(b"RIFF")
    monkeypatch.setattr(vi.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(vi, "get_torch_xpu_device", lambda: "xpu:0")

    captured = {}
    io_module = ModuleType("core.vocal_isolator_io")

    def fake_isolate(input_path, model_name, device, stop_event, progress_callback):
        captured.update(
            input_path=input_path,
            model_name=model_name,
            device=device,
            stop_event=stop_event,
            progress_callback=progress_callback,
        )
        output = tmp_path / "vocals.wav"
        output.write_bytes(b"RIFF")
        return str(output)

    io_module.isolate_vocals_xpu = fake_isolate
    monkeypatch.setitem(sys.modules, "core.vocal_isolator_io", io_module)

    result = vi.isolate_vocals(str(input_file), device="cpu")

    assert captured["device"] == "xpu:0"
    assert captured["model_name"] == "htdemucs"
    assert result == str(tmp_path / "vocals.wav")
