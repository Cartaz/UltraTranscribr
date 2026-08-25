"""Regression coverage for the final roadmap items."""
from __future__ import annotations

import queue
from unittest.mock import MagicMock

import pytest

from config.settings import Settings
from core.transcript_history import TranscriptHistoryStore
from core.whisper_backend import WhisperBackend


def _running_process():
    process = MagicMock()
    process.poll.return_value = None
    return process


def _history_session(store: TranscriptHistoryStore) -> str:
    return store.create_session(
        kind="file",
        model="medium",
        language="it",
        source="file",
        source_path="/tmp/example.wav",
    )


def test_session_names_are_optional_atomic_and_normalized(tmp_path) -> None:
    store = TranscriptHistoryStore(tmp_path / "history")
    session_id = _history_session(store)
    assert store.get_session(session_id)["name"] == ""
    assert store.set_name(session_id, "  Riunione   progetto  ") == "Riunione progetto"
    assert TranscriptHistoryStore(tmp_path / "history").get_session(session_id)["name"] == "Riunione progetto"
    assert store.set_name(session_id, "") == ""
    assert store.get_session(session_id)["name"] == ""


def test_session_name_search_is_case_insensitive_and_anded(tmp_path) -> None:
    store = TranscriptHistoryStore(tmp_path / "history")
    first = _history_session(store)
    second = _history_session(store)
    store.set_name(first, "Riunione Progetto Alpha")
    store.set_name(second, "Riunione Beta")
    assert [item["id"] for item in store.search("progetto alpha")] == [first]
    assert {item["id"] for item in store.search("RIUNIONE")} == {first, second}


def test_session_name_rejects_excessive_length(tmp_path) -> None:
    store = TranscriptHistoryStore(tmp_path / "history")
    session_id = _history_session(store)
    with pytest.raises(ValueError, match="120"):
        store.set_name(session_id, "x" * 121)


def test_backend_instance_settings_are_bounded_and_ports_fit() -> None:
    assert Settings(backend_instances=1).backend_instances == 1
    assert Settings(backend_instances=4).backend_instances == 4
    with pytest.raises(ValueError, match="backend_instances"):
        Settings(backend_instances=0)
    with pytest.raises(ValueError, match="backend_instances"):
        Settings(backend_instances=5)
    with pytest.raises(ValueError, match="porte"):
        Settings(server_port=65535, backend_instances=2)


def test_preload_model_defaults_off() -> None:
    assert Settings().preload_model is False
    assert Settings(preload_model=True).preload_model is True


def test_multi_instance_scheduler_uses_available_backends(monkeypatch, tmp_path) -> None:
    primary = WhisperBackend(Settings(backend_instances=2), tmp_path)
    primary._process = _running_process()
    auxiliary = WhisperBackend(Settings(server_port=8083), tmp_path, instance_label="-2")
    auxiliary._process = _running_process()
    primary._aux_backends = [auxiliary]
    pool: queue.Queue[WhisperBackend] = queue.Queue()
    pool.put(primary)
    pool.put(auxiliary)
    primary._pool_queue = pool

    monkeypatch.setattr(primary, "_transcribe_single", MagicMock(return_value="primary"))
    monkeypatch.setattr(auxiliary, "_transcribe_single", MagicMock(return_value="aux"))

    assert primary.transcribe_audio(b"one") == "primary"
    assert primary.transcribe_audio(b"two") == "aux"
    assert primary._transcribe_single.call_count == 1
    assert auxiliary._transcribe_single.call_count == 1


def test_multi_instance_queue_wait_callback_is_reported(monkeypatch, tmp_path) -> None:
    primary = WhisperBackend(Settings(backend_instances=2), tmp_path)
    primary._process = _running_process()
    auxiliary = WhisperBackend(Settings(server_port=8083), tmp_path, instance_label="-2")
    auxiliary._process = _running_process()
    primary._aux_backends = [auxiliary]
    pool: queue.Queue[WhisperBackend] = queue.Queue()
    pool.put(primary)
    pool.put(auxiliary)
    primary._pool_queue = pool
    monkeypatch.setattr(primary, "_transcribe_single", MagicMock(return_value="ok"))

    waits: list[float] = []
    assert primary.transcribe_audio(b"one", on_queue_wait=waits.append) == "ok"
    assert len(waits) == 1
    assert waits[0] >= 0.0


def test_backend_reconfigure_updates_launch_settings_only_when_stopped(tmp_path) -> None:
    backend = WhisperBackend(Settings(server_port=8082), tmp_path)
    backend.reconfigure(Settings(server_port=8090, backend_instances=2))
    assert backend.server_url.endswith(":8090")
    assert backend._settings.backend_instances == 2

    backend._process = _running_process()
    with pytest.raises(RuntimeError, match="Ferma whisper-server"):
        backend.reconfigure(Settings(server_port=8091))
