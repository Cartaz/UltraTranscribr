"""Contracts for source refresh, health and diagnostics."""
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


def test_frontend_refreshes_sources_on_live_entry_without_polling() -> None:
    script = (WEB / "multi_live.js").read_text(encoding="utf-8")
    assert 'if (name === "live") refreshAllAudioSources()' in script
    assert 'id = "source-refresh-all"' in script
    assert "probeAudioSource" in script
    for status in ("available", "playing", "disconnected"):
        assert status in script
    assert 'case "audio_devices_changed"' in script
    assert 'case "playback_streams_changed"' in script
    assert 'case "audio_source_health_changed"' in script
    assert "setInterval(" not in script


def test_meeting_source_editor_consumes_fresh_discovery_events() -> None:
    script = (WEB / "meeting.js").read_text(encoding="utf-8")
    assert "function meetingRenderSources" in script
    assert "filter(device => !!device?.is_mic)" in script
    assert "filter(device => !!device?.is_monitor)" in script
    assert 'name === "audio_devices_changed"' in script
    assert 'name === "playback_streams_changed"' in script
    assert "meetingRenderSources();" in script
    assert "meetingMicrophones = (bootstrap.devices || [])" in script
    assert "meetingStreams = bootstrap.playbackStreams || []" in script
    assert 'finishing: "Chiusura registrazione"' in script
    assert 'cancelling: "Annullamento"' in script


def test_source_probe_rules_live_in_core_discovery_service() -> None:
    bridge_source = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    application_source = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")
    service_source = (ROOT / "core" / "audio_discovery.py").read_text(encoding="utf-8")

    assert "evaluate_audio_source_health" in service_source
    assert "list_available_devices" in service_source
    assert "PactlRunner" in service_source
    assert "parse_playback_streams" in service_source
    assert "find_source" not in service_source
    assert "evaluate_audio_source_health" not in bridge_source
    assert "list_available_devices" not in bridge_source
    assert "find_source" not in bridge_source
    assert "self._application.probe_audio_source(" in bridge_source
    assert "cached_audio_source_health" not in bridge_source
    assert "request_audio_source_probe" not in bridge_source
    assert "cached_audio_source_health" in application_source
    assert "request_audio_source_probe" in application_source


def test_audio_diagnostics_live_below_bridge() -> None:
    bridge_source = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    application_source = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")
    diagnostics_source = (ROOT / "core" / "audio_diagnostics.py").read_text(encoding="utf-8")

    assert "self._application.run_audio_diagnostics()" in bridge_source
    assert "build_audio_diagnostics" not in bridge_source
    assert "build_audio_diagnostics(self.controller)" in application_source
    assert "debug_dump" not in bridge_source
    assert "=== playback streams ===" in diagnostics_source
    assert "=== UltraTranscribr live routing ===" in diagnostics_source
    assert "queue_wait" in diagnostics_source
    assert "routing=" in diagnostics_source
