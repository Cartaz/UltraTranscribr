"""Regression coverage for the final roadmap items."""
from __future__ import annotations

import queue
from unittest.mock import MagicMock

import pytest

from config.settings import Settings
from core.session_names import SessionNameStore
from core.whisper_backend import WhisperBackend


def _running_process():
    process = MagicMock()
    process.poll.return_value = None
    return process


def test_session_names_are_optional_atomic_and_normalized(tmp_path) -> None:
    store = SessionNameStore(tmp_path / "names.json")
    session = {"id": "session-1", "text": "ciao"}
    assert store.apply(session)["name"] == ""
    assert store.set("session-1", "  Riunione   progetto  ") == "Riunione progetto"
    assert SessionNameStore(tmp_path / "names.json").get("session-1") == "Riunione progetto"
    assert store.apply(session)["name"] == "Riunione progetto"
    assert store.set("session-1", "") == ""
    assert store.get("session-1") == ""


def test_session_name_search_is_case_insensitive_and_anded(tmp_path) -> None:
    store = SessionNameStore(tmp_path / "names.json")
    store.set("a", "Riunione Progetto Alpha")
    store.set("b", "Riunione Beta")
    assert store.matching_ids("progetto alpha") == {"a"}
    assert store.matching_ids("RIUNIONE") == {"a", "b"}


def test_session_name_rejects_excessive_length(tmp_path) -> None:
    store = SessionNameStore(tmp_path / "names.json")
    with pytest.raises(ValueError, match="120"):
        store.set("session-1", "x" * 121)


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
