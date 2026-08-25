"""Per-stream playback discovery and reversible PulseAudio/PipeWire routing.

A route lease moves one selected sink-input to a dedicated null sink, exposes
its monitor for capture, watches for replacement streams, and restores every
stream it moved when the lease closes.  All pactl commands flow through the
managed runner supplied by the application layer.
"""
from __future__ import annotations

import ast
import json
import logging
import os
import re
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from config.constants import AppMeta
from core.pactl import PactlRunner

logger = logging.getLogger(__name__)

_ROUTE_PREFIX = "ultratranscribr_capture_"
_ROUTE_STATE_PATH = AppMeta.CACHE_DIR / "audio_routes.json"
_PROPERTY_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*(.+?)\s*$")
_MODULE_SINK_RE = re.compile(r"(?:^|\s)sink_name=([^\s]+)")


def _unquote_property(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, str):
                return parsed
        except (SyntaxError, ValueError):
            pass
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def parse_sink_names(output: str) -> dict[int, str]:
    """Parse ``pactl list short sinks`` into ``index -> name``."""
    sinks: dict[int, str] = {}
    for line in str(output or "").splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        try:
            sinks[int(fields[0])] = fields[1]
        except ValueError:
            continue
    return sinks


@dataclass(frozen=True)
class PlaybackStream:
    """Normalized metadata for one PulseAudio/PipeWire sink-input."""

    id: int
    sink_index: int
    sink_name: str
    application_name: str
    media_name: str
    process_id: Optional[int]
    process_binary: str
    node_name: str
    corked: bool = False

    @property
    def display_name(self) -> str:
        app = self.application_name or self.process_binary or self.node_name
        if not app:
            app = f"Stream #{self.id}"
        if self.media_name and self.media_name.casefold() != app.casefold():
            return f"{app} — {self.media_name}"
        return app

    @property
    def state(self) -> str:
        return "paused" if self.corked else "playing"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sink_index": self.sink_index,
            "sink_name": self.sink_name,
            "application_name": self.application_name,
            "media_name": self.media_name,
            "process_id": self.process_id,
            "process_binary": self.process_binary,
            "node_name": self.node_name,
            "state": self.state,
            "display_name": self.display_name,
        }


def parse_playback_streams(
    output: str,
    sink_names: Optional[dict[int, str]] = None,
) -> list[PlaybackStream]:
    """Parse the verbose ``pactl list sink-inputs`` representation."""
    sinks = sink_names or {}
    records: list[PlaybackStream] = []
    current_id: Optional[int] = None
    sink_index = -1
    corked = False
    properties: dict[str, str] = {}
    in_properties = False

    def flush() -> None:
        nonlocal current_id, sink_index, corked, properties, in_properties
        if current_id is None:
            return
        pid: Optional[int] = None
        raw_pid = properties.get("application.process.id", "").strip()
        if raw_pid:
            try:
                pid = int(raw_pid)
            except ValueError:
                pid = None
        records.append(
            PlaybackStream(
                id=current_id,
                sink_index=sink_index,
                sink_name=sinks.get(sink_index, str(sink_index) if sink_index >= 0 else ""),
                application_name=properties.get("application.name", ""),
                media_name=properties.get("media.name", ""),
                process_id=pid,
                process_binary=properties.get("application.process.binary", ""),
                node_name=properties.get("node.name", ""),
                corked=corked,
            )
        )
        current_id = None
        sink_index = -1
        corked = False
        properties = {}
        in_properties = False

    for raw_line in str(output or "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("Sink Input #"):
            flush()
            try:
                current_id = int(stripped.split("#", 1)[1])
            except ValueError:
                current_id = None
            continue
        if current_id is None:
            continue
        if stripped == "Properties:":
            in_properties = True
            continue
        if not in_properties:
            if stripped.startswith("Sink:"):
                try:
                    sink_index = int(stripped.partition(":")[2].strip())
                except ValueError:
                    sink_index = -1
            elif stripped.startswith("Corked:"):
                corked = stripped.partition(":")[2].strip().casefold() == "yes"
            continue
        match = _PROPERTY_RE.match(line)
        if match:
            properties[match.group(1)] = _unquote_property(match.group(2))

    flush()
    return sorted(records, key=lambda stream: stream.id)


def _parse_modules(output: str) -> list[tuple[int, str, str]]:
    modules: list[tuple[int, str, str]] = []
    for line in str(output or "").splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            fields = line.split(maxsplit=2)
        if len(fields) < 2:
            continue
        try:
            module_id = int(fields[0])
        except ValueError:
            continue
        name = fields[1]
        args = fields[2] if len(fields) >= 3 else ""
        modules.append((module_id, name, args))
    return modules


def _route_sink_from_module(name: str, args: str) -> Optional[str]:
    if name != "module-null-sink":
        return None
    match = _MODULE_SINK_RE.search(args)
    if not match:
        return None
    sink_name = match.group(1)
    return sink_name if sink_name.startswith(_ROUTE_PREFIX) else None


class PulseAudioRouter:
    """Routing façade using one application-owned managed pactl runner."""

    def __init__(
        self,
        state_path: Path = _ROUTE_STATE_PATH,
        *,
        pactl_runner: Optional[PactlRunner] = None,
    ) -> None:
        self._state_path = Path(state_path)
        self._lock = threading.RLock()
        self._leases: dict[str, StreamRouteLease] = {}
        self._pactl = pactl_runner or PactlRunner()
        self._owns_pactl = pactl_runner is None

    def close(self) -> None:
        """Close any remaining leases and, when local, the command runner."""
        with self._lock:
            leases = list(self._leases.values())
        self._pactl.cancel_all()
        for lease in leases:
            try:
                lease.close()
            except Exception:
                logger.exception("Cleanup route %s fallito", lease.sink_name)
        if self._owns_pactl:
            self._pactl.close()

    def list_streams(self) -> list[PlaybackStream]:
        sink_output = self._pactl.run(["list", "short", "sinks"])
        sink_names = parse_sink_names(sink_output or "")
        stream_output = self._pactl.run(["list", "sink-inputs"])
        if stream_output is None:
            return []
        return parse_playback_streams(stream_output, sink_names)

    def get_stream(self, stream_id: int) -> PlaybackStream:
        wanted = int(stream_id)
        for stream in self.list_streams():
            if stream.id == wanted:
                return stream
        raise RuntimeError(
            f"Stream audio #{wanted} non più disponibile. Aggiorna l'elenco e riprova."
        )

    def isolate_stream(
        self,
        stream_id: int,
        status_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> "StreamRouteLease":
        selected = self.get_stream(stream_id)
        sink_name = f"{_ROUTE_PREFIX}{os.getpid()}_{uuid.uuid4().hex[:8]}"
        module_output = self._require_pactl(
            [
                "load-module",
                "module-null-sink",
                f"sink_name={sink_name}",
                "sink_properties=device.description=UltraTranscribr_Isolated",
            ]
        )
        try:
            module_id = int(module_output.splitlines()[0].strip())
        except (ValueError, IndexError) as exc:
            raise RuntimeError("pactl non ha restituito l'ID del null sink") from exc

        original_sink = selected.sink_name or str(selected.sink_index)
        try:
            self._move_stream(selected.id, sink_name)
        except Exception:
            self._pactl.run(["unload-module", str(module_id)])
            raise

        lease = StreamRouteLease(
            router=self,
            selected=selected,
            module_id=module_id,
            sink_name=sink_name,
            original_sink=original_sink,
            status_callback=status_callback,
        )
        with self._lock:
            self._leases[sink_name] = lease
            self._persist_state_locked()
        lease.start()
        return lease

    def cleanup_stale_routes(self) -> int:
        """Restore stale routed streams and unload old UltraTranscribr sinks."""
        modules_output = self._pactl.run(["list", "short", "modules"])
        if modules_output is None:
            return 0

        saved_routes = self._read_state()
        streams = {stream.id: stream for stream in self.list_streams()}
        default_sink = self._pactl.run(["get-default-sink"]) or ""

        for route in saved_routes:
            route_sink = str(route.get("sink_name") or "")
            original_sinks = route.get("original_sinks") or {}
            if not isinstance(original_sinks, dict):
                continue
            for raw_id, original in original_sinks.items():
                try:
                    stream_id = int(raw_id)
                except (TypeError, ValueError):
                    continue
                stream = streams.get(stream_id)
                if stream is None or stream.sink_name != route_sink:
                    continue
                target = str(original or default_sink).strip()
                if target:
                    self._pactl.run(["move-sink-input", str(stream_id), target])

        unloaded = 0
        failed_sinks: set[str] = set()
        for module_id, name, args in _parse_modules(modules_output):
            sink_name = _route_sink_from_module(name, args)
            if not sink_name:
                continue
            if self._pactl.run(["unload-module", str(module_id)]) is None:
                failed_sinks.add(sink_name)
            else:
                unloaded += 1

        if failed_sinks:
            remaining = [
                route
                for route in saved_routes
                if str(route.get("sink_name") or "") in failed_sinks
            ]
            self._write_state(remaining)
        else:
            self._write_state([])
        if unloaded:
            logger.info("Ripuliti %d sink virtuali UltraTranscribr obsoleti", unloaded)
        return unloaded

    def _require_pactl(self, args: list[str]) -> str:
        output = self._pactl.run(args)
        if output is None:
            raise RuntimeError(
                "Comando PipeWire/PulseAudio fallito: pactl " + " ".join(args)
            )
        return output

    def _move_stream(self, stream_id: int, sink: str) -> None:
        self._require_pactl(["move-sink-input", str(int(stream_id)), str(sink)])

    def _release_route(self, lease: "StreamRouteLease") -> None:
        streams = {stream.id: stream for stream in self.list_streams()}
        default_sink = (self._pactl.run(["get-default-sink"]) or "").strip()
        for stream_id, original_sink in lease.original_sinks.items():
            stream = streams.get(stream_id)
            if stream is None or stream.sink_name != lease.sink_name:
                continue
            target = str(original_sink or default_sink).strip()
            if target and self._pactl.run(
                ["move-sink-input", str(stream_id), target]
            ) is None:
                logger.warning(
                    "Impossibile ripristinare stream %s verso %s",
                    stream_id,
                    target,
                )
        if self._pactl.run(["unload-module", str(lease.module_id)]) is None:
            logger.warning("Impossibile scaricare il null sink %s", lease.sink_name)
        with self._lock:
            self._leases.pop(lease.sink_name, None)
            self._persist_state_locked()

    def _lease_changed(self) -> None:
        with self._lock:
            self._persist_state_locked()

    def _read_state(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return []
        routes = payload.get("routes", []) if isinstance(payload, dict) else []
        return [route for route in routes if isinstance(route, dict)]

    def _write_state(self, routes: list[dict[str, Any]]) -> None:
        if not routes:
            try:
                self._state_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.debug("Impossibile rimuovere stato routing: %s", exc)
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix="audio_routes.", suffix=".tmp", dir=self._state_path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"routes": routes}, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self._state_path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _persist_state_locked(self) -> None:
        self._write_state([lease.state_record() for lease in self._leases.values()])


class StreamRouteLease:
    """Lifetime of one isolated playback stream and its replacement watcher."""

    def __init__(
        self,
        *,
        router: PulseAudioRouter,
        selected: PlaybackStream,
        module_id: int,
        sink_name: str,
        original_sink: str,
        status_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self.router = router
        self.selected = selected
        self.module_id = int(module_id)
        self.sink_name = sink_name
        self.monitor_name = f"{sink_name}.monitor"
        self.original_sinks: dict[int, str] = {selected.id: original_sink}
        self.active_stream_id = selected.id
        self._status_callback = status_callback
        self._stop_event = threading.Event()
        self._closed = False
        self._close_lock = threading.Lock()
        self._last_status_key: Optional[tuple[str, Optional[int], str]] = None
        self._thread = threading.Thread(
            target=self._watch,
            daemon=True,
            name=f"AudioRouteWatch-{selected.id}",
        )

    def start(self) -> None:
        self._emit("playing" if not self.selected.corked else "paused", self.selected)
        self._thread.start()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self._stop_event.set()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.5)
        self.router._release_route(self)

    def state_record(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "sink_name": self.sink_name,
            "monitor_name": self.monitor_name,
            "selected_stream_id": self.selected.id,
            "active_stream_id": self.active_stream_id,
            "original_sinks": {str(k): v for k, v in self.original_sinks.items()},
        }

    def _watch(self) -> None:
        while not self._stop_event.wait(1.0):
            try:
                self._poll_once()
            except Exception as exc:
                logger.debug("Watchdog routing stream fallito: %s", exc)
                self._emit("disconnected", None, detail=str(exc))

    def _poll_once(self) -> None:
        streams = self.router.list_streams()
        by_id = {stream.id: stream for stream in streams}
        current = by_id.get(self.active_stream_id)
        if current is not None:
            if current.sink_name != self.sink_name:
                self.original_sinks[current.id] = (
                    current.sink_name or str(current.sink_index)
                )
                self.router._move_stream(current.id, self.sink_name)
                self.router._lease_changed()
                self._emit("reconnected", current)
                return
            self._emit(current.state, current)
            return

        replacement, ambiguous = self._find_replacement(streams)
        if replacement is None:
            self._emit("ambiguous" if ambiguous else "disconnected", None)
            return

        original = replacement.sink_name or str(replacement.sink_index)
        self.router._move_stream(replacement.id, self.sink_name)
        self.original_sinks[replacement.id] = original
        self.active_stream_id = replacement.id
        self.router._lease_changed()
        self._emit("reconnected", replacement)

    def _find_replacement(
        self,
        streams: list[PlaybackStream],
    ) -> tuple[Optional[PlaybackStream], bool]:
        scored: list[tuple[int, PlaybackStream]] = []
        for stream in streams:
            if stream.sink_name == self.sink_name:
                continue
            score = self._replacement_score(stream)
            if score >= 7:
                scored.append((score, stream))
        if not scored:
            return None, False
        best_score = max(score for score, _ in scored)
        best = [stream for score, stream in scored if score == best_score]
        if len(best) != 1:
            return None, True
        return best[0], False

    def _replacement_score(self, candidate: PlaybackStream) -> int:
        target = self.selected
        score = 0
        if target.process_id is not None and candidate.process_id == target.process_id:
            score += 8
        if (
            target.process_binary
            and candidate.process_binary.casefold() == target.process_binary.casefold()
        ):
            score += 4
        if (
            target.application_name
            and candidate.application_name.casefold() == target.application_name.casefold()
        ):
            score += 4
        if target.media_name and candidate.media_name.casefold() == target.media_name.casefold():
            score += 3
        if target.node_name and candidate.node_name.casefold() == target.node_name.casefold():
            score += 1
        return score

    def _emit(
        self,
        status: str,
        stream: Optional[PlaybackStream],
        *,
        detail: str = "",
    ) -> None:
        key = (status, stream.id if stream else None, detail)
        if key == self._last_status_key:
            return
        self._last_status_key = key
        if self._status_callback is None:
            return
        payload: dict[str, Any] = {
            "status": status,
            "selected_stream_id": self.selected.id,
            "active_stream_id": stream.id if stream else self.active_stream_id,
            "monitor": self.monitor_name,
            "detail": detail,
        }
        if stream is not None:
            payload["stream"] = stream.to_dict()
        try:
            self._status_callback(payload)
        except Exception:
            logger.exception("Callback stato routing fallita")
