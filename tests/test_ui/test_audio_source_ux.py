"""Phase 5 contracts for source refresh, health and diagnostics."""
from __future__ import annotations

from pathlib import Path

from core.audio_source_health import evaluate_audio_source_health


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "ui" / "web"


def test_system_source_probe_reports_available_automatic_monitor() -> None:
    result = evaluate_audio_source_health(
        source="system",
        automatic_source="default.monitor",
    )
    assert result["status"] == "available"
    assert result["label"] == "Disponibile · automatico"
    assert result["detail"] == "default.monitor"


def test_selected_application_stream_reports_playing_or_disconnected() -> None:
    streams = [
        {
            "id": 42,
            "display_name": "Browser · Video",
            "state": "playing",
        }
    ]
    playing = evaluate_audio_source_health(
        source="application",
        selection="42",
        streams=streams,
    )
    assert playing["status"] == "playing"
    assert playing["stream"]["id"] == 42

    missing = evaluate_audio_source_health(
        source="application",
        selection="42",
        streams=[],
    )
    assert missing["status"] == "disconnected"


def test_paused_application_stream_is_available_but_not_playing() -> None:
    result = evaluate_audio_source_health(
        source="application",
        selection="7",
        streams=[
            {
                "id": 7,
                "display_name": "Player · Pausa",
                "state": "paused",
            }
        ],
    )
    assert result["status"] == "available"
    assert result["label"] == "Disponibile · in pausa"


def test_manual_device_that_disappears_is_disconnected() -> None:
    result = evaluate_audio_source_health(
        source="microphone",
        selection="Mic B",
        devices=[
            {
                "name": "Mic A",
                "is_mic": True,
                "is_monitor": False,
            }
        ],
    )
    assert result["status"] == "disconnected"
    assert result["detail"] == "Mic B"


def test_no_automatic_system_source_is_actionable_disconnected_state() -> None:
    result = evaluate_audio_source_health(
        source="system",
        devices=[],
        automatic_source=None,
    )
    assert result["status"] == "disconnected"
    assert result["label"] == "Audio di sistema non disponibile"
    assert "Nessun ingresso compatibile" in result["detail"]


def test_frontend_refreshes_sources_on_live_entry_without_polling() -> None:
    script = (WEB / "multi_live.js").read_text(encoding="utf-8")
    assert 'if (name === "live") refreshAllAudioSources()' in script
    assert 'id = "source-refresh-all"' in script
    assert "probeAudioSource" in script
    for status in ("available", "playing", "disconnected"):
        assert status in script
    assert "setInterval(" not in script


def test_bridge_probe_uses_pure_health_evaluator() -> None:
    bridge_source = (ROOT / "ui" / "multi_session_bridge.py").read_text(
        encoding="utf-8"
    )
    assert "evaluate_audio_source_health" in bridge_source
    assert "probeAudioSource" in bridge_source
    assert "list_available_devices" in bridge_source
    assert "find_source" in bridge_source
    assert "list_playback_streams" in bridge_source


def test_audio_diagnostics_include_streams_and_live_routing() -> None:
    bridge_source = (ROOT / "ui" / "multi_session_bridge.py").read_text(
        encoding="utf-8"
    )
    assert "=== playback streams ===" in bridge_source
    assert "=== UltraTranscribr live routing ===" in bridge_source
    assert "queue_wait" in bridge_source
    assert "routing=" in bridge_source
