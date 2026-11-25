import wave

from config.constants import ProcessDefaults
from config.settings import Settings
from core.boundary_recovery import recover_boundary
from core.file_transcriber import FileTranscriberThread
from core.meeting_alignment import align_speakers, preserve_review_edits
from core.meeting_store import MeetingStore
from core.transcript_export import render_srt
from core.transcript_history import TranscriptHistoryStore
from core.whisper_backend import WhisperBackend


def segment(text, start, end, probability=0.99):
    tokens = text.split()
    step = (end - start) / len(tokens)
    return {
        "text": text,
        "start": start,
        "end": end,
        "words": [
            {
                "word": (" " if i else "") + token,
                "start": start + i * step,
                "end": start + (i + 1) * step,
                "probability": probability,
            }
            for i, token in enumerate(tokens)
        ],
    }


def test_novel_trimmed_words_and_approximate_timing_survive_review():
    history = [segment("dovevano far", 29, 30)]
    raw = segment("quel lavoro perché era più vicino", 0.2, 3.2)
    extra = recover_boundary([raw], history, 28, 30)
    normalized = FileTranscriberThread._normalize_chunk_segments(
        extra + [raw], chunk_offset_s=28, committed_before_s=30
    )
    assert (
        " ".join(s["text"] for s in normalized) == "quel lavoro perché era più vicino"
    )
    rows = align_speakers(
        normalized, [{"start": 0, "end": 40, "speaker_id": "SPEAKER_00"}]
    )
    assert rows[0]["quality_recovery"]["timing_requires_review"]
    assert "approximate_recovered_timing" in rows[0]["alignment_warnings"]


def test_overlap_repetitions_uncertain_and_missing_word_times():
    history = [segment("se voi", 28, 30)]
    raw = segment("se voi davvero volete", 0.1, 3.7)
    assert recover_boundary([raw], history, 28, 30) == []
    assert recover_boundary([segment("va bene", 3, 4)], history, 28, 30) == []
    assert (
        recover_boundary(
            [segment("altra ipotesi nuova", 0.1, 3.1, 0.2)], history, 28, 30
        )
        == []
    )
    missing = segment("altra ipotesi nuova", 0.1, 3.1)
    missing.pop("words")
    assert recover_boundary([missing], history, 28, 30) == []
    uncertain = segment("altra ipotesi nuova", 0.1, 3.1, float("nan"))
    assert recover_boundary([uncertain], history, 28, 30) == []


def test_nested_approximate_timing_is_not_reused_as_acoustic_evidence():
    nested = segment("parole già recuperate", 0.1, 1)
    nested["quality_recovery"] = {"timing_requires_review": True}
    assert recover_boundary([nested], [segment("altra frase", 28, 30)], 28, 30) == []


def test_recovery_notice_survives_saved_review_and_diarization_rerun(tmp_path):
    extra = recover_boundary(
        [segment("quel lavoro perché era più vicino", 0.2, 3.2)],
        [segment("dovevano far", 29, 30)],
        28,
        30,
    )
    segments = FileTranscriberThread._normalize_chunk_segments(
        extra, chunk_offset_s=28, committed_before_s=30
    )
    turns = [{"start": 0, "end": 40, "speaker_id": "SPEAKER_00"}]
    rows = align_speakers(segments, turns)
    history = TranscriptHistoryStore(tmp_path / "transcripts")
    store = MeetingStore(history, tmp_path / "meetings")
    session = store.create(
        model="medium", language="it", source="file", source_path="test.wav"
    )
    history.append_segments(session, segments)
    store.set_diarization(session, diarization_segments=turns, review_segments=rows)
    loaded = MeetingStore(history, tmp_path / "meetings").get(session)["meeting"][
        "review_segments"
    ]
    rerun = preserve_review_edits(
        loaded, align_speakers(history.get_session(session)["segments"], turns)
    )
    assert rerun[0]["quality_recovery"]["timing_requires_review"]
    assert "approximate_recovered_timing" in rerun[0]["alignment_warnings"]
    assert segments[0]["text"] in render_srt(history.get_session(session)["segments"])


def test_verbose_request_disables_unused_language_probabilities(tmp_path):
    backend = WhisperBackend(Settings(), tmp_path)
    body = backend._build_multipart(b"wav", "it", "BOUNDARY", verbose=True)
    assert b'name="no_language_probabilities"\r\n\r\ntrue\r\n' in body


def test_recovery_emits_a_persistable_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("ULTRATRANSCRIBR_EXPERIMENTAL_BOUNDARY_RECOVERY", "1")
    monkeypatch.setattr(ProcessDefaults, "FILE_SEGMENT_LENGTH_S", 3)
    monkeypatch.setattr(ProcessDefaults, "FILE_OVERLAP_DURATION_S", 1)
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as wf:
        wf.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wf.writeframes(bytes(16000 * 2 * 4))
    responses = iter(
        [
            ("dovevano far", [segment("dovevano far", 2, 3)]),
            (
                "quel lavoro perché era più vicino",
                [segment("quel lavoro perché era più vicino", 0.1, 1.9)],
            ),
        ]
    )
    events = []
    worker = FileTranscriberThread(
        str(path), None, Settings(), event_sink=lambda *event: events.append(event)
    )
    monkeypatch.setattr(worker, "_convert_to_pcm_wav", lambda _: str(path))
    monkeypatch.setattr(worker, "_request_checked_chunk", lambda *args: next(responses))
    worker._transcribe_progressively(str(path), 0)
    notices = [
        item
        for event, payload in events
        if event == "file_transcriber_quality"
        for item in payload
    ]
    assert len(notices) == 1
    assert notices[0]["reason"] == "overlap_boundary_recovered"
    assert notices[0]["timing_requires_review"] and not notices[0]["recovered"]
    history = TranscriptHistoryStore(tmp_path / "history")
    session = history.create_session(kind="file", model="large-v3", language="it")
    history.append_quality_issues(session, notices)
    reopened = TranscriptHistoryStore(history.root).get_session(session)
    assert reopened["quality_issues"] == notices
