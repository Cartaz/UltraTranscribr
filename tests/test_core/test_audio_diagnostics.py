"""Tests for read-only audio diagnostics reporting."""
from __future__ import annotations

from types import SimpleNamespace

from core.audio_diagnostics import build_audio_diagnostics


class FakeDiagnosticsSource:
    def __init__(self) -> None:
        self.discovery_calls = 0
        self.live_calls = 0
        self.meeting = SimpleNamespace(snapshot=lambda: {"status": "recording"})

    def audio_discovery_snapshot(self):
        self.discovery_calls += 1
        return {
            "devices": [
                {
                    "id": 2,
                    "name": "USB Mic",
                    "is_monitor": False,
                    "channels": 1,
                    "samplerate": 48000,
                }
            ],
            "streams": [
                {
                    "id": 41,
                    "display_name": "Firefox",
                    "process_id": 1234,
                    "process_binary": "firefox",
                    "sink_name": "alsa_output.demo",
                    "state": "RUNNING",
                }
            ],
        }

    def list_live_sessions(self, *, include_text: bool = False):
        self.live_calls += 1
        assert include_text is False
        return [
            {
                "id": "live-a",
                "source": "application",
                "status": "running",
                "terminal": False,
                "source_path": "Firefox",
                "sink": "ultratranscribr_route.monitor",
                "buffer_level": 12,
                "queue_wait_ms": 8,
            }
        ]


def test_audio_diagnostics_uses_cached_application_snapshots_only() -> None:
    source = FakeDiagnosticsSource()

    report = build_audio_diagnostics(source)

    assert source.discovery_calls == 1
    assert source.live_calls == 1
    assert "snapshot only; no hardware probe is started" in report
    assert "USB Mic" in report
    assert "Firefox" in report
    assert "routing=isolated" in report
    assert "queue_wait=8ms" in report
    assert "recording" in report


def test_audio_diagnostics_handles_empty_snapshots() -> None:
    source = FakeDiagnosticsSource()
    source.audio_discovery_snapshot = lambda: {"devices": [], "streams": []}
    source.list_live_sessions = lambda **_kwargs: []
    source.meeting = SimpleNamespace(snapshot=lambda: {})

    report = build_audio_diagnostics(source)

    assert "nessun input nella cache" in report
    assert "nessuno stream attivo nella cache" in report
    assert "nessuna sessione Live" in report
    assert "nessuna riunione runtime" in report
