# tests/conftest.py
"""Fixture condivise per i test dell'applicazione unificata."""

import pytest

from core.event_bus import EventBus


@pytest.fixture(autouse=True)
def _reset_event_bus():
    """Resetta il singleton EventBus prima e dopo ogni test."""
    EventBus.reset()
    yield
    EventBus.reset()


@pytest.fixture(autouse=True)
def _isolate_application_paths(tmp_path, monkeypatch):
    """A test must never save preferences or prune the user's real history."""
    from config.constants import AppMeta
    roots = {}
    for kind in ("CONFIG", "CACHE", "DATA"):
        roots[kind] = tmp_path / kind.lower()
        monkeypatch.setenv("XDG_" + kind + "_HOME", str(roots[kind]))
    for key, value in {
        "CONFIG_DIR": roots["CONFIG"] / "ultratranscribr",
        "CACHE_DIR": roots["CACHE"] / "ultratranscribr",
        "DATA_DIR": roots["DATA"] / "ultratranscribr",
        "SETTINGS_PATH": roots["CONFIG"] / "ultratranscribr/settings.json",
        "LOG_PATH": roots["CONFIG"] / "ultratranscribr/ultratranscribr.log",
        "DICTATION_PORTAL_STATE_PATH": roots["CONFIG"] / "ultratranscribr/dictation-portal.json",
        "DICTATION_METRICS_PATH": roots["DATA"] / "ultratranscribr/dictation-metrics.jsonl",
        "TRANSCRIPTS_DIR": roots["DATA"] / "ultratranscribr/transcripts",
        "RECORDINGS_DIR": roots["DATA"] / "ultratranscribr/recordings",
        "MODELS_DIR": roots["CACHE"] / "ultratranscribr/models/gguf",
        "DIARIZATION_MODELS_DIR": roots["CACHE"] / "ultratranscribr/models/diarization",
    }.items():
        monkeypatch.setattr(AppMeta, key, value)
