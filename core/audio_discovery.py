"""Non-blocking audio source discovery and health snapshots.

Hardware/process probing lives here so presentation code never runs
``sounddevice`` or ``pactl`` on the Qt GUI thread.  Discovery owns its pactl
runner, cached state and workers, which makes shutdown cancellation local and
deterministic instead of depending on daemon-thread process teardown.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

from config.settings import AudioSource, Settings
from core.audio_routing import parse_playback_streams, parse_sink_names
from core.audio_source_health import evaluate_audio_source_health
from core.pactl import PactlRunner
from core.sink_finder import find_microphone, list_available_devices

logger = logging.getLogger(__name__)

DeviceProvider = Callable[[], list[dict[str, Any]]]
StreamProvider = Callable[[], list[dict[str, Any]]]
SettingsProvider = Callable[[], Settings]
EventSink = Callable[[str, Any], None]
HealthEvaluator = Callable[..., dict[str, Any]]


class AudioDiscoveryService:
    """Own cached audio discovery state and all potentially blocking probes."""

    def __init__(
        self,
        *,
        settings_provider: SettingsProvider,
        stream_provider: Optional[StreamProvider] = None,
        event_sink: EventSink,
        device_provider: DeviceProvider = list_available_devices,
        health_evaluator: HealthEvaluator = evaluate_audio_source_health,
        pactl_runner: Optional[PactlRunner] = None,
    ) -> None:
        self._settings_provider = settings_provider
        # ``stream_provider`` is accepted for source compatibility with the
        # controller while discovery migrates away from router-owned I/O. It is
        # deliberately not used: this service must own the subprocesses it may
        # need to cancel during shutdown.
        del stream_provider
        self._event_sink = event_sink
        self._device_provider = device_provider
        self._health_evaluator = health_evaluator
        self._pactl = pactl_runner or PactlRunner()
        self._lock = threading.RLock()
        self._devices: list[dict[str, Any]] = []
        self._streams: list[dict[str, Any]] = []
        self._health: dict[tuple[str, str], dict[str, Any]] = {}
        self._refresh_thread: Optional[threading.Thread] = None
        self._refresh_pending_devices = False
        self._refresh_pending_streams = False
        self._probe_threads: dict[tuple[str, str], threading.Thread] = {}
        self._closed = False

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """Return an immediate copy of the latest discovery cache."""
        with self._lock:
            return {
                "devices": [dict(item) for item in self._devices],
                "streams": [dict(item) for item in self._streams],
            }

    def cached_health(self, source: str, selected_input: str = "") -> dict[str, Any]:
        """Return the latest matching health result without probing hardware."""
        key = self._health_key(source, selected_input)
        with self._lock:
            cached = self._health.get(key)
            if cached is not None:
                return dict(cached)
        return {
            "source": key[0],
            "selected_input": key[1],
            "status": "disconnected",
            "label": "Verifica in corso",
            "detail": "Controllo della sorgente audio in background.",
        }

    def request_refresh(self, *, devices: bool = True, streams: bool = True) -> None:
        """Schedule discovery and return immediately; concurrent requests coalesce."""
        if not devices and not streams:
            return
        with self._lock:
            if self._closed:
                return
            self._refresh_pending_devices = self._refresh_pending_devices or bool(devices)
            self._refresh_pending_streams = self._refresh_pending_streams or bool(streams)
            running = self._refresh_thread
            if running is not None and running.is_alive():
                return
            worker = threading.Thread(
                target=self._refresh_worker,
                daemon=True,
                name="AudioDiscoveryRefresh",
            )
            self._refresh_thread = worker
        worker.start()

    def request_probe(self, source: str, selected_input: str = "") -> None:
        """Schedule one source-health probe and return immediately."""
        key = self._health_key(source, selected_input)
        with self._lock:
            if self._closed:
                return
            running = self._probe_threads.get(key)
            if running is not None and running.is_alive():
                return
            worker = threading.Thread(
                target=self._probe_worker,
                args=key,
                daemon=True,
                name=f"AudioSourceProbe-{key[0]}",
            )
            self._probe_threads[key] = worker
        worker.start()

    def close(self) -> None:
        """Reject new work, terminate owned pactl children, then join workers."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            workers = [
                worker
                for worker in [self._refresh_thread, *self._probe_threads.values()]
                if worker is not None and worker.is_alive()
            ]
        self._pactl.close()
        for worker in workers:
            if worker is threading.current_thread():
                continue
            worker.join(timeout=0.75)
            if worker.is_alive():
                logger.warning(
                    "Worker discovery audio ancora attivo allo shutdown: %s",
                    worker.name,
                )

    def _refresh_worker(self) -> None:
        try:
            while True:
                with self._lock:
                    if self._closed:
                        return
                    want_devices = self._refresh_pending_devices
                    want_streams = self._refresh_pending_streams
                    self._refresh_pending_devices = False
                    self._refresh_pending_streams = False
                if not want_devices and not want_streams:
                    return
                if want_devices:
                    self._refresh_devices()
                if want_streams:
                    self._refresh_streams()
                with self._lock:
                    if self._closed:
                        return
                    if not self._refresh_pending_devices and not self._refresh_pending_streams:
                        return
        except Exception as exc:
            logger.exception("Discovery audio asincrona fallita")
            self._emit("audio_discovery_error", str(exc))
        finally:
            with self._lock:
                if self._refresh_thread is threading.current_thread():
                    self._refresh_thread = None

    def _refresh_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._closed:
                return []
        devices = [dict(item) for item in self._device_provider()]
        with self._lock:
            if self._closed:
                return devices
            self._devices = devices
        self._emit("audio_devices_changed", devices)
        return devices

    def _refresh_streams(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._closed:
                return []
        sink_output = self._pactl.run(["list", "short", "sinks"])
        sink_names = parse_sink_names(sink_output or "")
        stream_output = self._pactl.run(["list", "sink-inputs"])
        streams = (
            [stream.to_dict() for stream in parse_playback_streams(stream_output, sink_names)]
            if stream_output is not None
            else []
        )
        with self._lock:
            if self._closed:
                return streams
            self._streams = streams
        self._emit("playback_streams_changed", streams)
        return streams

    def _probe_worker(self, source: str, selected_input: str) -> None:
        key = (source, selected_input)
        try:
            settings = self._settings_provider()
            devices: list[dict[str, Any]] = []
            streams: list[dict[str, Any]] = []
            automatic_source: Optional[str] = None

            if source == AudioSource.APPLICATION.value:
                streams = self._refresh_streams()
            else:
                devices = self._refresh_devices()
                with self._lock:
                    if self._closed:
                        return
                if not selected_input:
                    automatic_source = self._resolve_automatic_source(settings, source)

            result = self._health_evaluator(
                source=source,
                selection=selected_input,
                devices=devices,
                streams=streams,
                automatic_source=automatic_source,
            )
            payload = {
                **dict(result),
                "source": source,
                "selected_input": selected_input,
            }
            with self._lock:
                if self._closed:
                    return
                self._health[key] = payload
            self._emit("audio_source_health_changed", payload)
        except Exception as exc:
            logger.exception("Probe sorgente audio fallito: %s", source)
            payload = {
                "source": source,
                "selected_input": selected_input,
                "status": "disconnected",
                "label": "Verifica non riuscita",
                "detail": str(exc),
            }
            with self._lock:
                if not self._closed:
                    self._health[key] = payload
            self._emit("audio_source_health_changed", payload)
        finally:
            with self._lock:
                current = self._probe_threads.get(key)
                if current is threading.current_thread():
                    self._probe_threads.pop(key, None)

    def _resolve_automatic_source(self, settings: Settings, source: str) -> Optional[str]:
        if source == AudioSource.MICROPHONE.value:
            return find_microphone(settings)
        if source != AudioSource.SYSTEM.value:
            return None

        sink_name = self._pactl.run(["get-default-sink"])
        if not sink_name:
            info = self._pactl.run(["info"])
            if info:
                for line in info.splitlines():
                    key, sep, value = line.partition(":")
                    if sep and key.strip().casefold() == "default sink":
                        sink_name = value.strip()
                        break
        if not sink_name:
            return None
        first = sink_name.splitlines()[0].strip()
        return f"{first}.monitor" if first else None

    @staticmethod
    def _health_key(source: str, selected_input: str) -> tuple[str, str]:
        normalized = (
            source if source in AudioSource.choices() else AudioSource.SYSTEM.value
        )
        return normalized, str(selected_input or "").strip()

    def _emit(self, event: str, payload: Any) -> None:
        with self._lock:
            if self._closed:
                return
        self._event_sink(event, payload)
