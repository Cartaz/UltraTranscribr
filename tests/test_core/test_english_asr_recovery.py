"""Qwen token-limit recovery must preserve source PCM and never hide decoder failures."""

from io import BytesIO
from pathlib import Path
from threading import Event
import wave

import numpy as np
import pytest

from config.settings import Settings
from core.english_asr import (
    ASRRecoveryExhaustedError,
    ASRTokenLimitError,
    EnglishASRBackend,
    _check_generation_end,
    _choose_split_frame,
    verify_decode_coverage,
)
from core.english_models import EnglishPipelineCancelled
from core.file_transcriber import FileTranscriberThread

RATE = 16000


def wav_pcm16(seconds: int = 30) -> tuple[bytes, bytes]:
    # Distinct nonzero samples make silent replacement/gaps observable in the hashes.
    pcm = np.arange(seconds * RATE, dtype=np.int16).astype("<i2").tobytes()
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(pcm)
    return buffer.getvalue(), pcm


def backend_with_decoder(monkeypatch, decoder):
    backend = EnglishASRBackend(Path("not-used-in-tests"), Event())
    backend.is_running = True
    monkeypatch.setattr(backend, "_decode_window", decoder)
    return backend


def test_generation_limit_is_checked_against_native_end_token():
    assert _check_generation_end(511, 99, [3, 4]) is False
    assert _check_generation_end(512, 3, [3, 4]) is True
    with pytest.raises(ASRTokenLimitError) as error:
        _check_generation_end(512, 99, [3, 4])
    assert error.value.tokens == 512


def test_silence_split_prefers_quiet_region_with_bounded_distance():
    samples = np.ones(30 * RATE, dtype=np.float32)
    samples[int(16.9 * RATE) : int(17.1 * RATE)] = 0
    split = _choose_split_frame(samples, RATE)
    assert abs(split / RATE - 17) <= 0.11
    assert 13 <= split / RATE <= 17


def test_normal_single_chunk_unchanged_and_audited(monkeypatch):
    audio, pcm = wav_pcm16()
    backend = backend_with_decoder(
        monkeypatch, lambda window, language: ("A normal sentence.", 12, True)
    )
    result = backend.transcribe_audio(audio, language="en", verbose=True)
    assert result["text"] == "A normal sentence."
    assert result["segments"] == [
        {"start": 0, "end": 30, "text": "A normal sentence."}
    ]
    assert result["recovered_from_token_limit"] is False
    assert [entry["status"] for entry in result["decoder_attempts"]] == ["completed"]
    verify_decode_coverage(pcm, result["decoder_attempts"])


def test_saturated_chunk_recovers_using_two_contiguous_windows(monkeypatch):
    audio, pcm = wav_pcm16()
    calls = []

    def decode(window, language):
        calls.append(len(window))
        if len(window) > 20 * RATE:
            raise ASRTokenLimitError(512)
        return f"part {len(calls)}", 20, True

    backend = backend_with_decoder(monkeypatch, decode)
    result = backend.transcribe_audio(audio, language="it", verbose=True)
    assert result["recovered_from_token_limit"] is True
    assert len(calls) == 3 and calls[0] == 30 * RATE
    assert calls[1] + calls[2] == 30 * RATE
    assert all(13 * RATE <= length <= 17 * RATE for length in calls[1:])
    assert [item["status"] for item in result["decoder_attempts"]] == [
        "token_limit", "completed", "completed"
    ]
    assert result["segments"][0]["end"] == result["segments"][1]["start"]
    assert result["segments"][-1]["end"] == 30
    assert len(result["segments"]) == 2
    assert "".join(result["text"].split()) == "".join(
        "".join(item["text"].split()) for item in result["segments"]
    )
    verify_decode_coverage(pcm, result["decoder_attempts"])


def test_multiple_splits_cover_original_audio_exactly_once(monkeypatch):
    audio, pcm = wav_pcm16()

    def decode(window, language):
        if len(window) > 10 * RATE:
            raise ASRTokenLimitError(512)
        return "short window", 17, True

    backend = backend_with_decoder(monkeypatch, decode)
    result = backend.transcribe_audio(audio, verbose=True)
    attempts = result["decoder_attempts"]
    assert sum(row["status"] == "token_limit" for row in attempts) == 3
    assert sum(row["status"] == "completed" for row in attempts) == 4
    assert len(result["segments"]) == 4
    assert result["generated_tokens"] == 68
    verify_decode_coverage(pcm, attempts)


def test_exhausted_recovery_fails_loudly_without_partial_success(monkeypatch):
    audio, _ = wav_pcm16()
    count = 0

    def decode(window, language):
        nonlocal count
        count += 1
        raise ASRTokenLimitError(512)

    backend = backend_with_decoder(monkeypatch, decode)
    with pytest.raises(ASRRecoveryExhaustedError, match="non termina"):
        backend.transcribe_audio(audio, verbose=True)
    assert 1 < count <= 15
    assert ASRRecoveryExhaustedError.retryable is False


def test_unrelated_decoder_error_is_not_relabelled_as_token_overflow(monkeypatch):
    audio, _ = wav_pcm16()

    def fail(window, language):
        raise RuntimeError("device lost")

    backend = backend_with_decoder(monkeypatch, fail)
    with pytest.raises(RuntimeError, match="device lost"):
        backend.transcribe_audio(audio, verbose=True)


def test_audio_coverage_rejects_missing_duplicate_and_modified_windows(monkeypatch):
    audio, pcm = wav_pcm16()

    def decode(window, language):
        if len(window) > 20 * RATE:
            raise ASRTokenLimitError(512)
        return "ok", 3, True

    backend = backend_with_decoder(monkeypatch, decode)
    attempts = backend.transcribe_audio(audio, verbose=True)["decoder_attempts"]
    completed = [dict(row) for row in attempts if row["status"] == "completed"]
    with pytest.raises(RuntimeError, match="non copre"):
        verify_decode_coverage(pcm, completed[:1])
    with pytest.raises(RuntimeError, match="perso o decodificato"):
        verify_decode_coverage(pcm, completed + completed)
    completed[0]["pcm_sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="non corrisponde"):
        verify_decode_coverage(pcm, completed)


def test_cancellation_interrupts_recursive_recovery(monkeypatch):
    audio, _ = wav_pcm16()
    cancellation = Event()
    backend = backend_with_decoder(monkeypatch, None)
    backend.cancel = cancellation

    def decode(window, language):
        cancellation.set()
        raise ASRTokenLimitError(512)

    monkeypatch.setattr(backend, "_decode_window", decode)
    with pytest.raises(EnglishPipelineCancelled):
        backend.transcribe_audio(audio, verbose=True)


def test_nonretryable_recovery_failure_does_not_retry_identical_audio():
    class FailedBackend:
        is_running = True

        def __init__(self):
            self.calls = 0

        def transcribe_audio(self, *args, **kwargs):
            self.calls += 1
            raise ASRRecoveryExhaustedError("bounded recovery exhausted")

    backend = FailedBackend()
    worker = FileTranscriberThread("unused.wav", backend, Settings(language="en"))
    wav, _ = wav_pcm16(1)
    with pytest.raises(RuntimeError, match="non recuperabile"):
        worker._request_chunk_verbose(wav, None)
    assert backend.calls == 1
