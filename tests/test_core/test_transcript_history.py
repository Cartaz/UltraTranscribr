"""Tests for crash-resistant transcript history persistence."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.transcript_history import TranscriptHistoryStore


def test_session_is_persisted_incrementally(tmp_path: Path) -> None:
    store = TranscriptHistoryStore(tmp_path / "history")
    session_id = store.create_session(
        kind="live",
        model="large-v3-turbo",
        language="it",
        source="firefox",
        source_path="speaker.monitor",
    )

    store.append_text(session_id, "prima parte")
    store.append_text(session_id, "seconda parte")
    store.set_status(session_id, "completed", terminal=True)

    session = store.get_session(session_id)
    assert session is not None
    assert session["text"] == "prima parte seconda parte"
    assert session["status"] == "completed"
    assert session["ended_at"] is not None

    persisted = json.loads((store.root / f"{session_id}.json").read_text(encoding="utf-8"))
    assert persisted["text"] == session["text"]


def test_recent_history_is_newest_first_and_uses_preview(tmp_path: Path) -> None:
    store = TranscriptHistoryStore(tmp_path / "history")
    first = store.create_session(kind="live", model="medium", language="it")
    store.append_text(first, "uno")
    second = store.create_session(kind="file", model="large-v3", language="en")
    store.append_text(second, "due " * 100)

    first_path = store.root / f"{first}.json"
    second_path = store.root / f"{second}.json"
    first_stat = first_path.stat()
    os.utime(first_path, (first_stat.st_atime, 1000))
    os.utime(second_path, (first_stat.st_atime, 2000))

    recent = store.list_recent(10)
    assert [item["id"] for item in recent] == [second, first]
    assert "text" not in recent[0]
    assert recent[0]["text_length"] > 0
    assert len(recent[0]["text_preview"]) <= 220


def test_invalid_session_id_cannot_escape_history_directory(tmp_path: Path) -> None:
    store = TranscriptHistoryStore(tmp_path / "history")
    with pytest.raises(ValueError):
        store.get_session("../../outside")


def test_corrupt_history_record_is_skipped(tmp_path: Path) -> None:
    store = TranscriptHistoryStore(tmp_path / "history")
    store.root.mkdir(parents=True)
    (store.root / "broken.json").write_text("{broken", encoding="utf-8")
    valid = store.create_session(kind="live", model="medium", language="it")

    recent = store.list_recent(10)
    assert [item["id"] for item in recent] == [valid]


def test_export_txt_is_atomic_and_session_can_be_deleted(tmp_path: Path) -> None:
    store = TranscriptHistoryStore(tmp_path / "history")
    session_id = store.create_session(kind="file", model="medium", language="it")
    store.append_text(session_id, "testo persistente")

    exported = store.export_text(session_id, tmp_path / "export")
    assert exported == tmp_path / "export.txt"
    assert exported.read_text(encoding="utf-8") == "testo persistente\n"

    assert store.delete_session(session_id) is True
    assert store.get_session(session_id) is None
    assert store.delete_session(session_id) is False


def test_retention_prunes_old_records_and_zero_disables_it(tmp_path: Path) -> None:
    store = TranscriptHistoryStore(tmp_path / "history")
    old_id = store.create_session(kind="live", model="medium", language="it")
    recent_id = store.create_session(kind="file", model="medium", language="it")

    old_path = store.root / f"{old_id}.json"
    data = json.loads(old_path.read_text(encoding="utf-8"))
    data["started_at"] = "2020-01-01T00:00:00+00:00"
    data["updated_at"] = "2020-01-01T00:00:00+00:00"
    data["ended_at"] = "2020-01-01T00:01:00+00:00"
    old_path.write_text(json.dumps(data), encoding="utf-8")

    assert store.prune_older_than(0) == 0
    assert store.get_session(old_id) is not None
    assert store.prune_older_than(30) == 1
    assert store.get_session(old_id) is None
    assert store.get_session(recent_id) is not None


def test_recovery_audio_inventory_and_safe_delete(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    wav = cache / "recovery-live-123.wav"
    wav.write_bytes(b"RIFF" + b"x" * 64)
    (cache / "other.wav").write_bytes(b"ignored")

    items = TranscriptHistoryStore.list_recovery_audio(cache)
    assert len(items) == 1
    assert items[0]["name"] == wav.name
    assert items[0]["path"] == str(wav)
    assert items[0]["size_bytes"] == wav.stat().st_size
    assert TranscriptHistoryStore.resolve_recovery_audio(wav, cache) == wav.resolve()

    assert TranscriptHistoryStore.delete_recovery_audio(wav, cache) is True
    assert not wav.exists()
    assert TranscriptHistoryStore.delete_recovery_audio(wav, cache) is False


def test_recovery_path_cannot_escape_cache(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    outside = tmp_path / "recovery-live-outside.wav"
    outside.write_bytes(b"RIFF")

    with pytest.raises(ValueError):
        TranscriptHistoryStore.resolve_recovery_audio(outside, cache)
