"""Contracts for source refresh, health and diagnostics."""
from __future__ import annotations

from pathlib import Path

from core.audio_source_health import evaluate_audio_source_health


ROOT = Path(__file__).resolve().parents[2]


def test_system_source_probe_reports_available_automatic_monitor() -> None:
    result = evaluate_audio_source_health(
        source="system",
        automatic_source="default.monitor",
    )
    assert result["status"] == "available"
    assert result["label"] == "Disponibile · automatico"
    assert result["detail"] == "default.monitor"


def test_selected_application_stream_reports_playing_or_disconnected() -> None:
    streams = [{"id": 42, "display_name": "Browser · Video", "state": "playing"}]
    playing = evaluate_audio_source_health(
        source="application", selection="42", streams=streams
    )
    assert playing["status"] == "playing"
    assert playing["stream"]["id"] == 42

    missing = evaluate_audio_source_health(
        source="application", selection="42", streams=[]
    )
    assert missing["status"] == "disconnected"


def test_paused_application_stream_is_available_but_not_playing() -> None:
    result = evaluate_audio_source_health(
        source="application",
        selection="7",
        streams=[{"id": 7, "display_name": "Player · Pausa", "state": "paused"}],
    )
    assert result["status"] == "available"
    assert result["label"] == "Disponibile · in pausa"


def test_manual_device_that_disappears_is_disconnected() -> None:
    result = evaluate_audio_source_health(
        source="microphone",
        selection="Mic B",
        devices=[{"name": "Mic A", "is_mic": True, "is_monitor": False}],
    )
    assert result["status"] == "disconnected"
    assert result["detail"] == "Mic B"


def test_no_automatic_system_source_is_actionable_disconnected_state() -> None:
    result = evaluate_audio_source_health(
        source="system", devices=[], automatic_source=None
    )
    assert result["status"] == "disconnected"
    assert result["label"] == "Audio di sistema non disponibile"
    assert "Nessun ingresso compatibile" in result["detail"]
