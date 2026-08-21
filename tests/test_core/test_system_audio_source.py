"""Tests for generalized system playback capture discovery."""
from __future__ import annotations

from types import SimpleNamespace

from config.settings import Settings
from core import sink_finder


class _Result:
    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def test_system_audio_uses_default_pactl_sink_monitor(monkeypatch) -> None:
    sink = "alsa_output.pci-0000_00_1f.3.analog-stereo"
    monitor = f"{sink}.monitor"

    def fake_run(command, **_kwargs):
        if command == ["pactl", "get-default-sink"]:
            return _Result(sink + "\n")
        if command == ["pactl", "list", "short", "sources"]:
            return _Result(f"45\t{monitor}\tPipeWire\ts16le 2ch 48000Hz\tIDLE\n")
        raise AssertionError(command)

    monkeypatch.setattr(sink_finder.subprocess, "run", fake_run)

    assert sink_finder.find_system_monitor() == monitor
    assert sink_finder.find_source(Settings(), "system") == monitor


def test_system_audio_falls_back_to_single_sounddevice_monitor(monkeypatch) -> None:
    def no_pactl(*_args, **_kwargs):
        raise FileNotFoundError("pactl")

    monkeypatch.setattr(sink_finder.subprocess, "run", no_pactl)
    monkeypatch.setattr(
        sink_finder.sd,
        "query_devices",
        lambda: [
            {"name": "Built-in Mic", "max_input_channels": 2, "hostapi": 0},
            {"name": "speakers.monitor", "max_input_channels": 2, "hostapi": 0},
        ],
    )
    monkeypatch.setattr(sink_finder.sd, "default", SimpleNamespace(device=(0, 0)))

    assert sink_finder.find_system_monitor() == "speakers.monitor"


def test_microphone_default_does_not_select_monitor(monkeypatch) -> None:
    devices = [
        {"name": "output.monitor", "max_input_channels": 2, "hostapi": 0},
        {"name": "USB Microphone", "max_input_channels": 1, "hostapi": 0},
    ]
    monkeypatch.setattr(sink_finder.sd, "query_devices", lambda: devices)
    monkeypatch.setattr(sink_finder.sd, "default", SimpleNamespace(device=(1, 0)))

    assert sink_finder.find_microphone(Settings(audio_source="microphone")) == "USB Microphone"


def test_multiple_monitors_without_default_are_not_guessed(monkeypatch) -> None:
    def no_pactl(*_args, **_kwargs):
        raise FileNotFoundError("pactl")

    monkeypatch.setattr(sink_finder.subprocess, "run", no_pactl)
    monkeypatch.setattr(
        sink_finder.sd,
        "query_devices",
        lambda: [
            {"name": "one.monitor", "max_input_channels": 2, "hostapi": 0},
            {"name": "two.monitor", "max_input_channels": 2, "hostapi": 0},
        ],
    )
    monkeypatch.setattr(sink_finder.sd, "default", SimpleNamespace(device=(-1, -1)))

    assert sink_finder.find_system_monitor() is None
