from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock

from core.file_segment_journal import FileSegmentJournal
from core.file_transcriber import FileTranscriberThread
from core.transcript_export import render_srt, render_vtt
from core.transcript_history import TranscriptHistoryStore
from core.transcript_postprocess import process_text


def _session(store: TranscriptHistoryStore, text: str = "Hello world") -> str:
    session_id = store.create_session(
        kind="file",
        model="large-v3-turbo",
        language="en",
        source="file",
        source_path="/tmp/example.wav",
    )
    store.append_text(session_id, text)
    return session_id


def test_old_history_record_without_phase9_fields_remains_readable(tmp_path: Path) -> None:
    store = TranscriptHistoryStore(tmp_path)
    payload = {
        "id": "legacy-session",
        "kind": "file",
        "started_at": "2026-08-20T10:00:00+00:00",
        "updated_at": "2026-08-20T10:00:00+00:00",
        "status": "completed",
        "model": "medium",
        "language": "it",
        "source": "file",
        "source_path": "/tmp/legacy.wav",
        "ended_at": "2026-08-20T10:01:00+00:00",
        "text": "vecchia trascrizione",
    }
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "legacy-session.json").write_text(json.dumps(payload), encoding="utf-8")

    loaded = store.get_session("legacy-session")

    assert loaded is not None
    assert loaded["text"] == "vecchia trascrizione"
    assert loaded["segments"] == []
    assert loaded["derived_outputs"] == {}


def test_segments_are_persisted_deduplicated_and_exported(tmp_path: Path) -> None:
    store = TranscriptHistoryStore(tmp_path / "history")
    session_id = _session(store, "First. Second.")
    store.append_segments(
        session_id,
        [
            {"start": 0.0, "end": 1.25, "text": "First."},
            {"start": 1.25, "end": 2.5, "text": "Second."},
            {"start": 0.0, "end": 1.25, "text": "First."},
        ],
    )

    loaded = store.get_session(session_id)
    assert loaded is not None
    assert len(loaded["segments"]) == 2

    srt = store.export_session(session_id, tmp_path / "out", format_name="srt")
    vtt = store.export_session(session_id, tmp_path / "captions", format_name="vtt")
    assert srt.suffix == ".srt"
    assert "00:00:00,000 --> 00:00:01,250" in srt.read_text(encoding="utf-8")
    assert vtt.read_text(encoding="utf-8").startswith("WEBVTT\n\n")
    assert "00:00:01.250 --> 00:00:02.500" in vtt.read_text(encoding="utf-8")


def test_subtitle_renderers_are_stable_and_ordered() -> None:
    segments = [
        {"start": 2.0, "end": 3.0, "text": "two"},
        {"start": 0.5, "end": 1.0, "text": "one"},
    ]
    srt = render_srt(segments)
    vtt = render_vtt(segments)
    assert srt.index("one") < srt.index("two")
    assert "00:00:00,500" in srt
    assert "00:00:00.500" in vtt


def test_search_matches_raw_text_and_metadata_with_and_semantics(tmp_path: Path) -> None:
    store = TranscriptHistoryStore(tmp_path)
    first = _session(store, "alpha beta gamma")
    second = store.create_session(
        kind="file",
        model="medium",
        language="it",
        source="file",
        source_path="/media/meeting-special.flac",
    )
    store.append_text(second, "contenuto diverso")

    assert [item["id"] for item in store.search("alpha gamma")] == [first]
    assert [item["id"] for item in store.search("meeting special")] == [second]
    assert store.search("alpha missing") == []


def test_postprocess_output_is_saved_without_overwriting_raw(tmp_path: Path) -> None:
    store = TranscriptHistoryStore(tmp_path)
    raw = "Uno.   Due? Tre! Quattro."
    session_id = _session(store, raw)
    derived = process_text(raw, "paragraphs")
    store.save_derived_output(session_id, "paragraphs", derived)

    loaded = store.get_session(session_id)
    assert loaded is not None
    assert loaded["text"] == raw
    assert loaded["derived_outputs"]["paragraphs"] == "Uno. Due? Tre!\n\nQuattro."

    exported = store.export_session(
        session_id,
        tmp_path / "derived.txt",
        format_name="txt",
        profile="paragraphs",
    )
    assert exported.read_text(encoding="utf-8") == "Uno. Due? Tre!\n\nQuattro.\n"


def test_chunk_segment_normalization_offsets_and_removes_overlap() -> None:
    segments = FileTranscriberThread._normalize_chunk_segments(
        [
            {"start": 0.0, "end": 1.0, "text": "overlap"},
            {"start": 1.0, "end": 3.0, "text": "new"},
            {"t0": 300, "t1": 400, "text": "ticks"},
        ],
        chunk_offset_s=28.0,
        committed_before_s=30.0,
    )
    assert segments == [
        {"start": 30.0, "end": 31.0, "text": "new"},
        {"start": 31.0, "end": 32.0, "text": "ticks"},
    ]


def test_file_segment_journal_writes_to_active_history_session(tmp_path: Path) -> None:
    history = TranscriptHistoryStore(tmp_path)
    session_id = _session(history)
    controller = MagicMock()
    controller._lock = threading.RLock()
    controller._file_history_id = session_id
    controller.history = history
    subscriptions = {}
    controller.subscribe.side_effect = lambda event, handler: subscriptions.setdefault(event, handler)

    journal = FileSegmentJournal(controller)
    subscriptions["file_transcriber_segments"](
        [{"start": 0.0, "end": 1.0, "text": "Hello"}]
    )

    loaded = history.get_session(session_id)
    assert loaded is not None
    assert loaded["segments"] == [{"start": 0.0, "end": 1.0, "text": "Hello"}]
    journal.close()
