import json
from unittest.mock import MagicMock

import numpy as np
import pytest

from config.settings import Settings
from core.file_transcriber import FileTranscriberThread
from core.transcript_history import TranscriptHistoryStore, TranscriptSession
from core.transcript_quality import quality_issues


def worker(backend, events=None, song=False):
    return FileTranscriberThread(
        "fixture.wav",
        backend,
        Settings(language="it"),
        song_mode=song,
        event_sink=lambda n, p: events.append((n, p)) if events is not None else None,
    )


def response(text, end=1):
    return {"text": text, "segments": [{"start": 0, "end": end, "text": text}]}


def test_short_real_repetitions_and_silence_are_not_quality_failures():
    text = "no no no no no, va bene"
    assert quality_issues(text, response(text)["segments"], b"\0\0" * 16000) == []
    assert quality_issues("", [], b"\0\0" * 16000) == []


def test_detects_single_token_and_phrase_loops_without_deleting_words():
    for text in ["di " * 122, "una frase in loop " * 4]:
        issues = quality_issues(text, response(text)["segments"])
        assert any(issue["reason"] == "repetition_loop" for issue in issues)


def test_detects_energetic_uncovered_audio_as_warning_not_certain_speech():
    pcm = (np.ones(48000) * 1200).astype("<i2").tobytes()
    assert quality_issues("", [], pcm) == [
        {"reason": "uncovered_audio", "start": 0, "end": 3}
    ]


def test_loop_recovery_resets_prompt_preserves_original_and_uses_backend_text_only():
    backend = MagicMock()
    backend.transcribe_audio.side_effect = [
        response("di " * 12),
        response("parole effettivamente recuperate"),
    ]
    events = []
    text, segments = worker(backend, events)._request_checked_chunk(
        b"\0\0" * 16000, "vecchio contesto", 60
    )
    assert text == "parole effettivamente recuperate"
    assert backend.transcribe_audio.call_count == 2
    assert backend.transcribe_audio.call_args_list[1].kwargs["prompt"] is None
    assert segments[0]["quality_recovery"]["original"]["text"] == "di " * 12
    assert segments[0]["quality_recovery"]["accepted"]
    assert events[0][1][0]["start"] == 60 and events[0][1][0]["recovered"]
    json.dumps(segments)  # Recovery provenance must not contain reference cycles.


def test_failed_quality_retry_keeps_original_loop_and_an_explicit_warning():
    backend = MagicMock()
    backend.transcribe_audio.return_value = response("di " * 12)
    text, segments = worker(backend)._request_checked_chunk(b"\0\0" * 16000, None, 0)
    assert text == "di " * 12
    assert not segments[0]["quality_recovery"]["accepted"]
    assert segments[0]["quality_issues"][0]["reason"] == "repetition_loop"
    assert backend.transcribe_audio.call_count == 2


def test_partial_recovery_failure_cannot_replace_full_original_with_a_prefix():
    backend = MagicMock()
    backend.transcribe_audio.side_effect = [
        response("di " * 12, 30),
        response("solo un inizio", 12),
        RuntimeError("failure"),
        RuntimeError("failure"),
        RuntimeError("failure"),
    ]
    instance = worker(backend)
    instance._stop_event.wait = lambda timeout: False
    text, segments = instance._request_checked_chunk(b"\0\0" * (30 * 16000), None, 0)
    assert text == "di " * 12
    assert not segments[0]["quality_recovery"]["accepted"]


def test_song_repetitions_do_not_trigger_automatic_recovery():
    backend = MagicMock()
    backend.transcribe_audio.return_value = response("ritornello " * 20)
    text, _ = worker(backend, song=True)._request_checked_chunk(
        b"\0\0" * 16000, None, 0
    )
    assert text == "ritornello " * 20 and backend.transcribe_audio.call_count == 1


def test_overlap_is_trimmed_at_whole_word_boundary_not_inside_a_subword():
    segments = FileTranscriberThread._normalize_chunk_segments(
        [
            {
                "start": 0,
                "end": 2,
                "text": "una parola",
                "words": [
                    {"word": " una", "start": 0, "end": 0.5},
                    {"word": " par", "start": 0.5, "end": 1},
                    {"word": "ola", "start": 1, "end": 2},
                ],
            }
        ],
        chunk_offset_s=10,
        committed_before_s=11,
    )
    assert segments[0]["text"] == "parola"
    assert segments[0]["words"][0]["word"].strip() == "parola"


def test_quality_metadata_survives_normalization_for_review_and_restart():
    segments = FileTranscriberThread._normalize_chunk_segments(
        [
            {
                "start": 0,
                "end": 1,
                "text": "di di di",
                "quality_issues": [{"reason": "repetition_loop"}],
                "quality_recovery": {
                    "accepted": False,
                    "original": {"text": "di di di"},
                },
            }
        ],
        chunk_offset_s=10,
        committed_before_s=0,
    )
    assert segments[0]["quality_issues"][0]["reason"] == "repetition_loop"
    assert not segments[0]["quality_recovery"]["accepted"]


def test_energy_coverage_understands_whisper_cpp_tick_and_millisecond_formats():
    pcm = (np.ones(48000) * 1200).astype("<i2").tobytes()
    for timing in ({"t0": 0, "t1": 300}, {"offsets": {"from": 0, "to": 3000}}):
        assert quality_issues("parlato", [{"text": "parlato", **timing}], pcm) == []


def test_untranscribed_chunk_warning_survives_restart_without_changing_legacy_record_schema(
    tmp_path,
):
    store = TranscriptHistoryStore(tmp_path / "history")
    sid = store.create_session(kind="meeting", model="large-v3", language="it")
    issue = {"reason": "uncovered_audio", "start": 30, "end": 35, "recovered": False}
    store.append_quality_issues(sid, [issue])
    restarted = TranscriptHistoryStore(store.root)
    assert restarted.get_session(sid)["quality_issues"] == [issue]
    # Existing installations can still open the canonical JSON during a
    # rollback: quality metadata is a sidecar, not an unknown dataclass field.
    TranscriptSession(**json.loads((store.root / f"{sid}.json").read_text()))


def test_quality_checks_tolerate_malformed_optional_backend_records():
    assert quality_issues("ciao", [None, {"text": "ciao", "words": [None]}]) == [
        {"reason": "word_text_mismatch", "start": 0, "end": 0}
    ]


def test_native_engine_crash_preserves_diagnostic_instead_of_retrying_dead_process():
    backend = MagicMock()
    backend.is_running = False
    backend.transcribe_audio.side_effect = RuntimeError("UR_RESULT_ERROR_UNKNOWN · Error OP GET_ROWS")
    with pytest.raises(RuntimeError, match="GET_ROWS"):
        worker(backend)._request_chunk_verbose(b"wav", None)
    backend.transcribe_audio.assert_called_once()
