import threading

from config.settings import AudioSource, Settings
from core.audio_discovery import AudioDiscoveryService


class FakePactl:
    def __init__(self, outputs=None) -> None:
        self.outputs = outputs or {}
        self.calls: list[tuple[str, ...]] = []
        self.cancelled = False
        self.closed = False

    def run(self, args, *, timeout=10.0):
        del timeout
        self.calls.append(tuple(args))
        if self.closed:
            return None
        return self.outputs.get(tuple(args))

    def cancel_all(self) -> None:
        self.cancelled = True

    def close(self) -> None:
        self.closed = True


def test_refresh_returns_before_slow_device_provider_finishes() -> None:
    entered = threading.Event()
    release = threading.Event()
    changed = threading.Event()
    events: list[tuple[str, object]] = []

    def devices():
        entered.set()
        release.wait(timeout=2.0)
        return [{"name": "Mic", "is_mic": True, "is_monitor": False}]

    def emit(name, payload):
        events.append((name, payload))
        if name == "audio_devices_changed":
            changed.set()

    service = AudioDiscoveryService(
        settings_provider=Settings,
        event_sink=emit,
        device_provider=devices,
        pactl_runner=FakePactl(),
    )

    service.request_refresh(devices=True, streams=False)
    assert entered.wait(timeout=1.0)
    assert service.snapshot()["devices"] == []

    release.set()
    assert changed.wait(timeout=1.0)
    assert service.snapshot()["devices"][0]["name"] == "Mic"
    assert events[-1][0] == "audio_devices_changed"
    service.close()


def test_probe_returns_cached_state_while_slow_microphone_resolution_runs(
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    health_ready = threading.Event()
    events: list[tuple[str, object]] = []

    def resolve(_settings):
        entered.set()
        release.wait(timeout=2.0)
        return "Mic"

    monkeypatch.setattr("core.audio_discovery.find_microphone", resolve)

    def emit(name, payload):
        events.append((name, payload))
        if name == "audio_source_health_changed":
            health_ready.set()

    service = AudioDiscoveryService(
        settings_provider=Settings,
        event_sink=emit,
        device_provider=lambda: [
            {"name": "Mic", "is_mic": True, "is_monitor": False}
        ],
        pactl_runner=FakePactl(),
    )

    service.request_probe(AudioSource.MICROPHONE.value, "")
    assert entered.wait(timeout=1.0)
    cached = service.cached_health(AudioSource.MICROPHONE.value, "")
    assert cached["label"] == "Verifica in corso"

    release.set()
    assert health_ready.wait(timeout=1.0)
    result = service.cached_health(AudioSource.MICROPHONE.value, "")
    assert result["status"] == "available"
    assert result["label"] == "Disponibile · automatico"
    assert result["detail"] == "Mic"
    service.close()


def test_application_probe_uses_shared_pactl_and_refreshes_cache() -> None:
    health_ready = threading.Event()
    events: list[tuple[str, object]] = []
    pactl = FakePactl(
        {
            ("list", "short", "sinks"): "7\talsa_output.speakers\tmodule\ts16le 2ch 48000Hz\tRUNNING",
            ("list", "sink-inputs"): '''Sink Input #17
\tSink: 7
\tCorked: no
\tProperties:
\t\tapplication.name = "Player"
\t\tmedia.name = "Track"
\t\tapplication.process.id = "123"
\t\tapplication.process.binary = "player"
\t\tnode.name = "Player"
''',
        }
    )

    def emit(name, payload):
        events.append((name, payload))
        if name == "audio_source_health_changed":
            health_ready.set()

    service = AudioDiscoveryService(
        settings_provider=Settings,
        event_sink=emit,
        device_provider=lambda: [],
        pactl_runner=pactl,
    )

    service.request_probe(AudioSource.APPLICATION.value, "17")
    assert health_ready.wait(timeout=1.0)

    streams = service.snapshot()["streams"]
    assert streams[0]["id"] == 17
    result = service.cached_health(AudioSource.APPLICATION.value, "17")
    assert result["status"] == "playing"
    assert result["detail"] == "Player — Track"
    assert ("list", "short", "sinks") in pactl.calls
    assert ("list", "sink-inputs") in pactl.calls
    assert any(name == "playback_streams_changed" for name, _ in events)
    service.close()


def test_system_probe_resolves_default_monitor_with_shared_pactl() -> None:
    ready = threading.Event()
    pactl = FakePactl({("get-default-sink",): "alsa_output.main"})
    service = AudioDiscoveryService(
        settings_provider=Settings,
        event_sink=lambda name, _payload: ready.set()
        if name == "audio_source_health_changed"
        else None,
        device_provider=lambda: [
            {
                "name": "alsa_output.main.monitor",
                "is_mic": False,
                "is_monitor": True,
            }
        ],
        pactl_runner=pactl,
    )

    service.request_probe(AudioSource.SYSTEM.value, "")
    assert ready.wait(timeout=1.0)
    result = service.cached_health(AudioSource.SYSTEM.value, "")
    assert result["status"] == "available"
    assert result["detail"] == "alsa_output.main.monitor"
    service.close()


def test_close_cancels_shared_pactl_without_owning_its_lifetime() -> None:
    called = threading.Event()
    pactl = FakePactl()
    service = AudioDiscoveryService(
        settings_provider=Settings,
        event_sink=lambda _name, _payload: None,
        device_provider=lambda: called.set() or [],
        pactl_runner=pactl,
    )
    service.close()
    service.request_refresh()
    service.request_probe(AudioSource.SYSTEM.value, "")
    assert pactl.cancelled is True
    assert pactl.closed is False
    assert not called.wait(timeout=0.05)
