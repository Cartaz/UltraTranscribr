"""Tests for generalized system playback capture discovery."""
from __future__ import annotations

from types import SimpleNamespace

from config.settings import Settings
from core import sink_finder


class FakePactlRunner:
    def __init__(self, responses=None) -> None:
        self.responses = responses or {}

    def run(self, args: list[str], *, timeout: float = 10.0):
        del timeout
        return self.responses.get(tuple(args))

    def cancel_all(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_system_audio_uses_default_pactl_sink_monitor() -> None:
    sink = "alsa_output.pci-0000_00_1f.3.analog-stereo"
    monitor = f"{sink}.monitor"
    pactl = FakePactlRunner(
        {
            ("get-default-sink",): sink + "\n",
            ("list", "short", "sources"): f"45\t{monitor}\tPipeWire\ts16le 2ch 48000Hz\tIDLE\n",
        }
    )

    assert sink_finder.find_system_monitor(pactl_runner=pactl) == monitor
    assert sink_finder.find_source(Settings(), "system", pactl_runner=pactl) == monitor


def test_system_audio_falls_back_to_single_sounddevice_monitor(monkeypatch) -> None:
    pactl = FakePactlRunner()
    monkeypatch.setattr(
        sink_finder.sd,
        "query_devices",
        lambda: [
            {"name": "Built-in Mic", "max_input_channels": 2, "hostapi": 0},
            {"name": "speakers.monitor", "max_input_channels": 2, "hostapi": 0},
        ],
    )
    monkeypatch.setattr(sink_finder.sd, "default", SimpleNamespace(device=(0, 0)))

    assert sink_finder.find_system_monitor(pactl_runner=pactl) == "speakers.monitor"


def test_microphone_default_does_not_select_monitor(monkeypatch) -> None:
    devices = [
        {"name": "output.monitor", "max_input_channels": 2, "hostapi": 0},
        {"name": "USB Microphone", "max_input_channels": 1, "hostapi": 0},
    ]
    monkeypatch.setattr(sink_finder.sd, "query_devices", lambda: devices)
    monkeypatch.setattr(sink_finder.sd, "default", SimpleNamespace(device=(1, 0)))

    assert sink_finder.find_microphone(Settings(audio_source="microphone")) == "USB Microphone"


def test_multiple_monitors_without_default_are_not_guessed(monkeypatch) -> None:
    pactl = FakePactlRunner()
    monkeypatch.setattr(
        sink_finder.sd,
        "query_devices",
        lambda: [
            {"name": "one.monitor", "max_input_channels": 2, "hostapi": 0},
            {"name": "two.monitor", "max_input_channels": 2, "hostapi": 0},
        ],
    )
    monkeypatch.setattr(sink_finder.sd, "default", SimpleNamespace(device=(-1, -1)))

    assert sink_finder.find_system_monitor(pactl_runner=pactl) is None
