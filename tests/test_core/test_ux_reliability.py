"""UX roadmap: persisted review commands, source fidelity and lossless backlog."""

import json
from unittest.mock import Mock

import numpy as np
import pytest
import soundfile as sf

from config.constants import AppMeta
from config.settings import Settings
from core.buffer_manager import BufferManager
from core.meeting_store import MeetingStore
from core.microphone_recording import MicrophoneRecorder
from core.review_timeline import ReviewTimeline
from core.transcriber import TranscriberThread
from tests.test_core.test_meeting_store import _meeting


def test_fifty_review_edits_survive_restart_with_persistent_undo_and_redo(tmp_path):
    history, store, sid = _meeting(tmp_path)
    rows = [
        {
            "start": i,
            "end": i + 0.8,
            "text": f"originale {i}",
            "speaker_id": "SPEAKER_00",
        }
        for i in range(50)
    ]
    store.set_diarization(sid, diarization_segments=[], review_segments=rows)
    edits = {i: f"  correzione {i}\n" for i in range(50)}
    store.edit_review_segments(sid, edits)
    reopened = MeetingStore(history, store.root)
    assert [r["text"] for r in reopened.get(sid)["meeting"]["review_segments"]] == list(
        edits.values()
    )
    reopened.undo_review(sid)
    assert [r["text"] for r in reopened.get(sid)["meeting"]["review_segments"]] == [
        r["text"] for r in rows
    ]
    MeetingStore(history, store.root).undo_review(sid, redo=True)
    saved = store.get(sid)["meeting"]
    assert saved["review_revision"] == 3
    assert saved["review_segments"][49]["raw_text"] == "originale 49"
    assert saved["review_segments"][49]["text"] == edits[49]
    assert history.get_session(sid)["text"] == "Testo raw originale"


def test_failed_atomic_command_does_not_advance_undo_or_change_document(
    tmp_path, monkeypatch
):
    _, store, sid = _meeting(tmp_path)
    before = store._path(sid).read_bytes()
    monkeypatch.setattr(store, "_write", Mock(side_effect=OSError("Disk full")))
    with pytest.raises(OSError):
        store.edit_review_segment(sid, 0, "da conservare")
    assert store._path(sid).read_bytes() == before


def test_new_edit_invalidates_redo_and_rerun_conflict_is_explicit(tmp_path):
    _, store, sid = _meeting(tmp_path)
    store.edit_review_segment(sid, 0, "prima")
    store.undo_review(sid)
    store.edit_review_segment(sid, 0, "seconda")
    assert store.get(sid)["meeting"]["review_redo"] == []
    store.set_diarization(
        sid,
        diarization_segments=[],
        review_segments=[{"start": 12, "end": 15, "text": "altra voce"}],
    )
    before = store._path(sid).read_bytes()
    with pytest.raises(ValueError, match="non compatibile"):
        store.undo_review(sid)
    assert store._path(sid).read_bytes() == before


def test_speaker_names_and_assignments_share_the_document_undo_history(tmp_path):
    _, store, sid = _meeting(tmp_path)
    store.set_speaker_name(sid, "SPEAKER_00", "Anna")
    store.set_review_speaker_override(sid, 0, "SPEAKER_01")
    store.undo_review(sid)
    assert "speaker_override" not in store.get(sid)["meeting"]["review_segments"][0]
    store.undo_review(sid)
    assert "SPEAKER_00" not in store.get(sid)["meeting"]["speaker_names"]
    store.undo_review(sid, redo=True)
    assert store.get(sid)["meeting"]["speaker_names"]["SPEAKER_00"] == "Anna"


def test_original_is_byte_identical_and_retention_never_deletes_external_source(
    tmp_path,
):
    _, store, sid = _meeting(tmp_path)
    source = tmp_path / "source-stereo.wav"
    sf.write(source, np.ones((4800, 2), dtype=np.float32) * 0.1, 48000)
    original = source.read_bytes()
    store.retain_original(sid, source)
    path = store.playback_path(sid)
    assert path.read_bytes() == original
    assert sf.info(path).samplerate == 48000 and sf.info(path).channels == 2
    assert store.recording_path(sid) is None  # analysis audio is independent
    store.delete_audio(sid)
    assert source.read_bytes() == original and not path.exists()
    assert store.playback_path(sid) is None


def test_missing_or_tampered_original_is_not_silently_replaced_by_analysis_audio(
    tmp_path,
):
    _, store, sid = _meeting(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"original audio")
    store.retain_original(sid, source)
    path = store.playback_path(sid)
    path.write_bytes(b"tampered audio")  # same length: size alone is insufficient
    assert store.playback_path(sid) is None
    path.unlink()
    assert store.playback_path(sid) is None


def test_native_rate_journal_recovers_at_48khz_after_crash(tmp_path):
    recorder = MicrophoneRecorder("native", root=tmp_path, sample_rate=48000)
    recorder.write(np.ones(4800, dtype=np.float32) * 0.1)
    recorder.abandon()
    recovered = MicrophoneRecorder.recover_orphaned(tmp_path)
    assert len(recovered) == 1
    assert recovered[0].sample_rate == 48000
    assert recovered[0].duration_s == pytest.approx(0.1)
    assert sf.info(recovered[0].path).samplerate == 48000


def test_backlog_measures_samples_with_variable_chunks_and_disk_spill():
    buffer = BufferManager(warn_threshold=2, max_memory_chunks=1)
    try:
        for size in (1600, 3200, 800):
            buffer.put(np.zeros(size, dtype=np.float32))
        assert buffer.pending_seconds == pytest.approx(0.35)
        assert buffer.buffer_level == 150 and buffer.spooled_chunks == 2
        buffer.get_nowait()
        assert buffer.pending_seconds == pytest.approx(0.25)
        buffer.get_nowait()
        buffer.get_nowait()
        assert buffer.pending_seconds == 0 and buffer.spooled_chunks == 0
    finally:
        buffer.close()


def test_stop_recovers_current_segment_and_every_spooled_chunk(tmp_path):
    buffer = BufferManager(max_memory_chunks=1)
    worker = TranscriberThread(buffer, Mock(), Settings(), session_id="recover")
    worker._current_segment = [np.ones(1600, dtype=np.float32) * 0.1]
    for size in (3200, 4800, 6400):
        buffer.put(np.ones(size, dtype=np.float32) * 0.2)
    worker.stop()
    worker.run()
    files = list(AppMeta.CACHE_DIR.glob("recovery-live-recover-*.wav"))
    assert len(files) == 1
    assert sf.info(files[0]).frames == 16000
    assert buffer.is_empty
    buffer.close()


def test_timeline_handles_overlap_boundaries_backwards_seeking_and_gaps():
    timeline = ReviewTimeline(
        [{"start": 42, "end": 58}, {"start": 50, "end": 63}, {"start": 58, "end": 80}]
    )
    assert timeline.at(42) == [0]
    assert timeline.at(52) == [0, 1]
    assert timeline.at(58) == [1, 2]
    assert timeline.at(99) == []
    assert timeline.at(52) == [0, 1]
    assert timeline.at(float("nan")) == []
    assert timeline.at(0) == []


def test_readable_history_title_does_not_mutate_id_or_invent_source(tmp_path):
    history, _, sid = _meeting(tmp_path)
    record = history.get_session(sid)
    assert record["display_name"].startswith("Microfono · ")
    assert record["id"] == sid
    history.set_name(sid, "Titolo corretto")
    assert history.list_recent()[0]["display_name"] == "Titolo corretto"
    assert "display_name" not in json.loads(history._path(sid).read_text())


def test_catchup_batches_only_existing_backlog_and_preserves_every_sample(monkeypatch):
    buffer = BufferManager(max_memory_chunks=2)
    worker = TranscriberThread(buffer, Mock(), Settings())
    # Forty producer chunks spill to disk. Capture is finished: drain the FIFO.
    for _ in range(40):
        buffer.put(np.ones(48000, dtype=np.float32) * 0.1)
    buffer.close_input()
    committed = []

    def flush(final):
        committed.append(worker._segment_sample_count)
        worker._current_segment.clear()
        worker._segment_sample_count = 0

    monkeypatch.setattr(worker, "_flush_segment", flush)
    assert worker._loop()
    worker._flush_segment(True)
    assert sum(committed) == 40 * 48000
    assert max(committed) > worker._segment_samples
    assert max(committed) + worker._overlap_samples <= 30 * 16000
    assert len(committed) <= 6  # ordinary 12 s bodies would require ten requests
    buffer.close()


def test_catchup_does_not_extend_the_target_without_queued_audio(monkeypatch):
    buffer = BufferManager()
    worker = TranscriberThread(buffer, Mock(), Settings())
    buffer.put(np.ones(48000, dtype=np.float32))
    original_get = buffer.get

    def one_chunk(*args, **kwargs):
        chunk = original_get(*args, **kwargs)
        worker.stop()
        return chunk

    monkeypatch.setattr(buffer, "get", one_chunk)
    assert not worker._loop()
    assert worker._active_segment_target == worker._segment_samples
    buffer.close()
