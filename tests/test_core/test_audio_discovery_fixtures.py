"""Parser coverage using captured-style pactl/PipeWire fixtures."""
from __future__ import annotations

from pathlib import Path

from core import audio_routing, sink_finder


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pactl"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_sink_names_fixture_maps_indexes_to_pipewire_names() -> None:
    sinks = audio_routing.parse_sink_names(_fixture("sinks-short.txt"))
    assert sinks == {
        42: "alsa_output.pci-0000_00_1f.3.analog-stereo",
        77: "bluez_output.11_22_33_44_55_66.1",
    }


def test_sink_input_fixture_preserves_metadata_and_pause_state() -> None:
    sinks = audio_routing.parse_sink_names(_fixture("sinks-short.txt"))
    streams = audio_routing.parse_playback_streams(_fixture("sink-inputs.txt"), sinks)

    assert [stream.id for stream in streams] == [101, 205]
    firefox, vlc = streams
    assert firefox.sink_name == "alsa_output.pci-0000_00_1f.3.analog-stereo"
    assert firefox.application_name == "Firefox"
    assert firefox.media_name == 'Video "Demo"'
    assert firefox.process_id == 4242
    assert firefox.process_binary == "firefox"
    assert firefox.state == "playing"
    assert firefox.display_name == 'Firefox — Video "Demo"'

    assert vlc.sink_name == "bluez_output.11_22_33_44_55_66.1"
    assert vlc.process_id is None
    assert vlc.state == "paused"
    assert vlc.display_name == "VLC media player — Musica"


def test_router_list_streams_combines_short_sinks_and_verbose_inputs(monkeypatch) -> None:
    responses = {
        ("list", "short", "sinks"): _fixture("sinks-short.txt"),
        ("list", "sink-inputs"): _fixture("sink-inputs.txt"),
    }
    monkeypatch.setattr(
        audio_routing,
        "_run_pactl",
        lambda args, timeout=10.0: responses.get(tuple(args)),
    )

    streams = audio_routing.PulseAudioRouter().list_streams()
    assert len(streams) == 2
    assert streams[0].id == 101
    assert streams[1].corked is True


def test_default_monitor_is_resolved_from_pactl_fixtures(monkeypatch) -> None:
    responses = {
        ("get-default-sink",): "alsa_output.pci-0000_00_1f.3.analog-stereo",
        ("list", "short", "sources"): _fixture("sources-short.txt"),
    }
    monkeypatch.setattr(
        sink_finder,
        "_run_pactl",
        lambda args: responses.get(tuple(args)),
    )

    assert (
        sink_finder._find_default_monitor_via_pactl()
        == "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor"
    )


def test_default_sink_parser_falls_back_to_pactl_info(monkeypatch) -> None:
    info = "Server String: /run/user/1000/pulse/native\nDefault Sink: bluez_output.demo\n"
    monkeypatch.setattr(
        sink_finder,
        "_run_pactl",
        lambda args: None if args == ["get-default-sink"] else info,
    )

    assert sink_finder._default_sink_name_via_pactl() == "bluez_output.demo"


def test_module_fixture_only_identifies_ultratranscribr_null_sink() -> None:
    modules = audio_routing._parse_modules(_fixture("modules-short.txt"))
    assert len(modules) == 3
    route_sinks = [
        audio_routing._route_sink_from_module(name, args)
        for _, name, args in modules
    ]
    assert route_sinks == [None, "ultratranscribr_capture_1234_deadbeef", None]


def test_malformed_parser_lines_are_ignored_without_losing_valid_streams() -> None:
    sinks = audio_routing.parse_sink_names("bad line\n5\tvalid.sink\tPipeWire")
    assert sinks == {5: "valid.sink"}

    streams = audio_routing.parse_playback_streams(
        "Sink Input #bad\n\tSink: nope\nSink Input #9\n\tSink: 5\n\tCorked: no\n\tProperties:\n\t\tapplication.name = \"App\"",
        sinks,
    )
    assert len(streams) == 1
    assert streams[0].id == 9
    assert streams[0].sink_name == "valid.sink"
