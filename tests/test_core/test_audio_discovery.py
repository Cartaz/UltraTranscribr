import threading

from config.settings import AudioSource, Settings
from core.audio_discovery import AudioDiscoveryService


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
        stream_provider=lambda: [],
        event_sink=emit,
        device_provider=devices,
    )

    service.request_refresh(devices=True, streams=False)
    assert entered.wait(timeout=1.0)
    assert service.snapshot()["devices"] == []

    release.set()
    assert changed.wait(timeout=1.0)
    assert service.snapshot()["devices"][0]["name"] == "Mic"
    assert events[-1][0] == "audio_devices_changed"
    service.close()


def test_probe_returns_cached_state_while_slow_resolution_runs() -> None:
    entered = threading.Event()
    release = threading.Event()
    health_ready = threading.Event()
    events: list[tuple[str, object]] = []

    def resolve(settings, source):
        del settings
        assert source == AudioSource.MICROPHONE.value
        entered.set()
        release.wait(timeout=2.0)
        return "Mic"

    def emit(name, payload):
        events.append((name, payload))
        if name == "audio_source_health_changed":
            health_ready.set()

    service = AudioDiscoveryService(
        settings_provider=Settings,
        stream_provider=lambda: [],
        event_sink=emit,
        device_provider=lambda: [
            {"name": "Mic", "is_mic": True, "is_monitor": False}
        ],
        source_resolver=resolve,
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


def test_application_probe_refreshes_stream_cache_and_health() -> None:
    health_ready = threading.Event()
    events: list[tuple[str, object]] = []

    def emit(name, payload):
        events.append((name, payload))
        if name == "audio_source_health_changed":
            health_ready.set()

    stream = {
        "id": 17,
        "display_name": "Player",
        "state": "playing",
    }
    service = AudioDiscoveryService(
        settings_provider=Settings,
        stream_provider=lambda: [stream],
        event_sink=emit,
        device_provider=lambda: [],
    )

    service.request_probe(AudioSource.APPLICATION.value, "17")
    assert health_ready.wait(timeout=1.0)

    assert service.snapshot()["streams"] == [stream]
    result = service.cached_health(AudioSource.APPLICATION.value, "17")
    assert result["status"] == "playing"
    assert result["detail"] == "Player"
    assert any(name == "playback_streams_changed" for name, _ in events)
    service.close()


def test_close_rejects_new_discovery_work() -> None:
    called = threading.Event()
    service = AudioDiscoveryService(
        settings_provider=Settings,
        stream_provider=lambda: [],
        event_sink=lambda _name, _payload: None,
        device_provider=lambda: called.set() or [],
    )
    service.close()
    service.request_refresh()
    service.request_probe(AudioSource.SYSTEM.value, "")
    assert not called.wait(timeout=0.05)
