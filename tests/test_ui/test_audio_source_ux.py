"""Phase 5 contracts for source refresh, health and diagnostics."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from config.settings import Settings
from ui.multi_session_bridge import MultiSessionBackendBridge


def _bridge() -> tuple[MultiSessionBackendBridge, MagicMock]:
    controller = MagicMock()
    controller.settings = Settings()
    controller.subscribe = MagicMock()
    bridge = MultiSessionBackendBridge(controller)
    return bridge, controller


def test_system_source_probe_reports_available_automatic_monitor() -> None:
    bridge, _controller = _bridge()
    with patch("ui.multi_session_bridge.list_available_devices", return_value=[]), \
         patch("ui.multi_session_bridge.find_source", return_value="default.monitor"):
        result = json.loads(bridge.probeAudioSource("system", ""))
    assert result["status"] == "available"
    assert result["detail"] == "default.monitor"


def test_selected_application_stream_reports_playing_or_disconnected() -> None:
    bridge, controller = _bridge()
    controller.list_playback_streams.return_value = [
        {
            "id": 42,
            "display_name": "Browser · Video",
            "state": "playing",
        }
    ]
    playing = json.loads(bridge.probeAudioSource("application", "42"))
    assert playing["status"] == "playing"
    assert playing["stream"]["id"] == 42

    controller.list_playback_streams.return_value = []
    missing = json.loads(bridge.probeAudioSource("application", "42"))
    assert missing["status"] == "disconnected"


def test_manual_device_that_disappears_is_disconnected() -> None:
    bridge, _controller = _bridge()
    with patch(
        "ui.multi_session_bridge.list_available_devices",
        return_value=[{"name": "Mic A", "is_mic": True, "is_monitor": False}],
    ):
        result = json.loads(bridge.probeAudioSource("microphone", "Mic B"))
    assert result["status"] == "disconnected"
    assert result["detail"] == "Mic B"


def test_frontend_refreshes_sources_on_live_entry_without_polling() -> None:
    script = ( __import__("pathlib").Path(__file__).resolve().parents[2] / "ui" / "web" / "multi_live.js").read_text(encoding="utf-8")
    assert 'if (name === "live") refreshAllAudioSources()' in script
    assert 'id = "source-refresh-all"' in script
    assert 'probeAudioSource' in script
    assert '"available", "playing", "disconnected"' in script
    assert "setInterval(" not in script


def test_audio_diagnostics_include_streams_and_live_routing() -> None:
    bridge_source = (__import__("pathlib").Path(__file__).resolve().parents[2] / "ui" / "multi_session_bridge.py").read_text(encoding="utf-8")
    assert "=== playback streams ===" in bridge_source
    assert "=== UltraTranscribr live routing ===" in bridge_source
    assert "queue_wait" in bridge_source
    assert "routing=" in bridge_source
