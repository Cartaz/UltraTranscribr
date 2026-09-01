from config.settings import AudioSource
from core.audio_inputs import AudioInputResolver, AudioInputSelection
from core.audio_routing import PlaybackStream


class _Route:
    monitor_name = "meeting_app.monitor"

    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _Router:
    def __init__(self) -> None:
        self.stream_calls = 0
        self.isolate_calls = 0
        self.route = _Route()

    def get_stream(self, stream_id: int) -> PlaybackStream:
        self.stream_calls += 1
        assert stream_id == 42
        return PlaybackStream(
            id=42,
            sink_index=1,
            sink_name="alsa_output.test",
            application_name="Browser",
            media_name="Meeting",
            process_id=123,
            process_binary="browser",
            node_name="browser-node",
        )

    def isolate_stream(self, stream_id: int, status_callback=None):
        self.isolate_calls += 1
        assert stream_id == 42
        if status_callback:
            status_callback({"status": "isolated"})
        return self.route


def test_resolver_uses_sink_resolution_for_microphone_and_system() -> None:
    calls = []
    resolver = AudioInputResolver(
        _Router(),
        lambda selected, source: calls.append((selected, source)) or selected or f"auto-{source}",
    )

    mic = resolver.acquire(
        AudioInputSelection(source=AudioSource.MICROPHONE.value, selected_input="Mic A")
    )
    system = resolver.acquire(AudioInputSelection(source=AudioSource.SYSTEM.value))

    assert mic.capture_sink == "Mic A"
    assert mic.descriptor.source_path == "Mic A"
    assert system.capture_sink == "auto-system"
    assert calls == [("Mic A", "microphone"), (None, "system")]
    mic.close()
    system.close()


def test_application_is_described_before_route_move_and_restored_once() -> None:
    router = _Router()
    events = []
    resolver = AudioInputResolver(router, lambda selected, source: "unused")
    selection = AudioInputSelection(
        source=AudioSource.APPLICATION.value,
        stream_id=42,
        label="Meet remoti",
    )

    lease = resolver.acquire(selection, status_callback=events.append)

    assert router.stream_calls == 1
    assert router.isolate_calls == 1
    assert lease.capture_sink == "meeting_app.monitor"
    assert lease.descriptor.source_path == "Browser — Meeting"
    assert lease.descriptor.label == "Meet remoti"
    assert events == [{"status": "isolated"}]

    lease.close()
    lease.close()
    assert router.route.close_calls == 1


def test_application_requires_stream_id() -> None:
    try:
        AudioInputSelection(source=AudioSource.APPLICATION.value)
    except ValueError as exc:
        assert "stream" in str(exc).lower()
    else:
        raise AssertionError("application input without stream id must be rejected")
