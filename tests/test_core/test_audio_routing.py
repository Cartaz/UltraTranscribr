"""Deterministic tests for per-application PulseAudio routing."""
from __future__ import annotations

import json
from dataclasses import replace

import core.audio_routing as routing
from core.audio_routing import PlaybackStream, PulseAudioRouter, StreamRouteLease


PACTl_STREAMS = r'''
Sink Input #42
	Driver: PipeWire
	Sink: 7
	Corked: no
	Properties:
		application.name = "Firefox"
		media.name = "YouTube — Interview"
		application.process.id = "1234"
		application.process.binary = "firefox"
		node.name = "Firefox"
Sink Input #43
	Driver: PipeWire
	Sink: 7
	Corked: yes
	Properties:
		application.name = "Firefox"
		media.name = "Second tab"
		application.process.id = "1234"
		application.process.binary = "firefox"
		node.name = "Firefox"
'''


def stream(
    stream_id: int = 42,
    *,
    sink: str = "alsa_output.speakers",
    pid: int = 1234,
    media: str = "YouTube — Interview",
) -> PlaybackStream:
    return PlaybackStream(
        id=stream_id,
        sink_index=7,
        sink_name=sink,
        application_name="Firefox",
        media_name=media,
        process_id=pid,
        process_binary="firefox",
        node_name="Firefox",
        corked=False,
    )


def test_parse_playback_streams_keeps_each_sink_input_separate() -> None:
    streams = routing.parse_playback_streams(
        PACTl_STREAMS,
        {7: "alsa_output.speakers"},
    )

    assert [item.id for item in streams] == [42, 43]
    assert streams[0].application_name == "Firefox"
    assert streams[0].media_name == "YouTube — Interview"
    assert streams[0].process_id == 1234
    assert streams[0].process_binary == "firefox"
    assert streams[0].sink_name == "alsa_output.speakers"
    assert streams[0].state == "playing"
    assert streams[1].state == "paused"
    assert streams[0].display_name == "Firefox — YouTube — Interview"


def test_isolate_stream_moves_only_selected_stream_and_close_restores_it(
    monkeypatch,
    tmp_path,
) -> None:
    router = PulseAudioRouter(tmp_path / "routes.json")
    original = stream()
    captured: dict[str, str] = {}
    commands: list[list[str]] = []
    list_calls = 0

    def fake_list_streams():
        nonlocal list_calls
        list_calls += 1
        if list_calls == 1:
            return [original]
        return [replace(original, sink_name=captured["route_sink"])]

    def fake_pactl(args: list[str], *, timeout: float = 10.0):
        del timeout
        commands.append(args)
        if args[:2] == ["load-module", "module-null-sink"]:
            captured["route_sink"] = next(
                part.split("=", 1)[1]
                for part in args
                if part.startswith("sink_name=")
            )
            return "77"
        if args == ["get-default-sink"]:
            return "alsa_output.speakers"
        return ""

    monkeypatch.setattr(router, "list_streams", fake_list_streams)
    monkeypatch.setattr(routing, "_run_pactl", fake_pactl)
    monkeypatch.setattr(StreamRouteLease, "start", lambda self: None)

    lease = router.isolate_stream(42)

    assert lease.monitor_name == f"{captured['route_sink']}.monitor"
    assert ["move-sink-input", "42", captured["route_sink"]] in commands
    assert (tmp_path / "routes.json").is_file()

    lease.close()

    assert ["move-sink-input", "42", "alsa_output.speakers"] in commands
    assert ["unload-module", "77"] in commands
    assert not (tmp_path / "routes.json").exists()


def test_disappeared_stream_reconnects_only_to_unique_match(monkeypatch, tmp_path) -> None:
    router = PulseAudioRouter(tmp_path / "routes.json")
    selected = stream()
    replacement = stream(99)
    events: list[dict] = []
    moves: list[tuple[int, str]] = []
    lease = StreamRouteLease(
        router=router,
        selected=selected,
        module_id=77,
        sink_name="ultratranscribr_capture_test",
        original_sink=selected.sink_name,
        status_callback=events.append,
    )

    monkeypatch.setattr(router, "list_streams", lambda: [replacement])
    monkeypatch.setattr(router, "_move_stream", lambda stream_id, sink: moves.append((stream_id, sink)))
    monkeypatch.setattr(router, "_lease_changed", lambda: None)

    lease._poll_once()

    assert moves == [(99, "ultratranscribr_capture_test")]
    assert lease.active_stream_id == 99
    assert lease.original_sinks[99] == "alsa_output.speakers"
    assert events[-1]["status"] == "reconnected"
    assert events[-1]["stream"]["id"] == 99


def test_ambiguous_replacement_never_routes_arbitrarily(monkeypatch, tmp_path) -> None:
    router = PulseAudioRouter(tmp_path / "routes.json")
    selected = stream()
    events: list[dict] = []
    moves: list[tuple[int, str]] = []
    lease = StreamRouteLease(
        router=router,
        selected=selected,
        module_id=77,
        sink_name="ultratranscribr_capture_test",
        original_sink=selected.sink_name,
        status_callback=events.append,
    )
    candidates = [stream(50, media="A"), stream(51, media="B")]

    monkeypatch.setattr(router, "list_streams", lambda: candidates)
    monkeypatch.setattr(router, "_move_stream", lambda stream_id, sink: moves.append((stream_id, sink)))

    lease._poll_once()

    assert moves == []
    assert lease.active_stream_id == 42
    assert events[-1]["status"] == "ambiguous"


def test_cleanup_stale_route_restores_stream_then_unloads_module(
    monkeypatch,
    tmp_path,
) -> None:
    state_path = tmp_path / "routes.json"
    route_sink = "ultratranscribr_capture_stale"
    state_path.write_text(
        json.dumps(
            {
                "routes": [
                    {
                        "module_id": 77,
                        "sink_name": route_sink,
                        "monitor_name": route_sink + ".monitor",
                        "selected_stream_id": 42,
                        "active_stream_id": 42,
                        "original_sinks": {"42": "alsa_output.speakers"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    router = PulseAudioRouter(state_path)
    routed = stream(sink=route_sink)
    commands: list[list[str]] = []

    monkeypatch.setattr(router, "list_streams", lambda: [routed])

    def fake_pactl(args: list[str], *, timeout: float = 10.0):
        del timeout
        commands.append(args)
        if args == ["list", "short", "modules"]:
            return (
                "77\tmodule-null-sink\t"
                f"sink_name={route_sink} sink_properties=device.description=UltraTranscribr_Isolated"
            )
        if args == ["get-default-sink"]:
            return "alsa_output.speakers"
        return ""

    monkeypatch.setattr(routing, "_run_pactl", fake_pactl)

    assert router.cleanup_stale_routes() == 1
    assert ["move-sink-input", "42", "alsa_output.speakers"] in commands
    assert ["unload-module", "77"] in commands
    assert not state_path.exists()
