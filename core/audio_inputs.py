"""Shared resolution and reversible routing for capture inputs.

This module owns the source-selection rules shared by Live and Meeting.  It does
not capture or transcribe audio; callers acquire a lease, use its capture sink,
and close the lease when the workflow ends.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from config.settings import AudioSource
from core.audio_routing import PulseAudioRouter, StreamRouteLease

SinkResolver = Callable[[Optional[str], str], str]
RouteStatusCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class AudioInputSelection:
    """User-selected logical audio input, independent of native routing."""

    source: str
    selected_input: str = ""
    stream_id: Optional[int] = None
    label: str = ""

    def __post_init__(self) -> None:
        source = str(self.source or "").strip()
        if source not in set(AudioSource.choices()):
            raise ValueError(f"sorgente audio non valida: {source}")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "selected_input", str(self.selected_input or "").strip())
        object.__setattr__(self, "label", str(self.label or "").strip())
        if source == AudioSource.APPLICATION.value:
            if self.stream_id is None:
                raise ValueError("Seleziona uno stream applicazione")
            object.__setattr__(self, "stream_id", int(self.stream_id))
        else:
            object.__setattr__(self, "stream_id", None)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AudioInputSelection":
        if not isinstance(value, Mapping):
            raise ValueError("sorgente audio non valida")
        raw_stream = value.get("stream_id")
        stream_id: Optional[int]
        if raw_stream in (None, ""):
            stream_id = None
        else:
            try:
                stream_id = int(raw_stream)
            except (TypeError, ValueError) as exc:
                raise ValueError("stream applicazione non valido") from exc
        return cls(
            source=str(value.get("source") or ""),
            selected_input=str(value.get("selected_input") or ""),
            stream_id=stream_id,
            label=str(value.get("label") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "selected_input": self.selected_input,
            "stream_id": self.stream_id,
            "label": self.label,
        }


@dataclass(frozen=True)
class AudioInputDescriptor:
    """Resolved human/native metadata before capture starts."""

    source: str
    source_path: str
    sink_name: Optional[str]
    stream_id: Optional[int]
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_path": self.source_path,
            "sink_name": self.sink_name,
            "stream_id": self.stream_id,
            "label": self.label,
        }


class AudioInputLease:
    """One acquired native input route with deterministic cleanup."""

    def __init__(
        self,
        descriptor: AudioInputDescriptor,
        capture_sink: Optional[str],
        route: Optional[StreamRouteLease] = None,
    ) -> None:
        self.descriptor = descriptor
        self.capture_sink = capture_sink
        self.route = route
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        route = self.route
        self.route = None
        if route is not None:
            route.close()


class AudioInputResolver:
    """Deep source adapter shared by Live and Meeting workflows."""

    def __init__(self, router: PulseAudioRouter, sink_resolver: SinkResolver) -> None:
        self._router = router
        self._sink_resolver = sink_resolver

    def describe(self, selection: AudioInputSelection) -> AudioInputDescriptor:
        if selection.source == AudioSource.APPLICATION.value:
            assert selection.stream_id is not None
            stream = self._router.get_stream(selection.stream_id)
            return AudioInputDescriptor(
                source=selection.source,
                source_path=stream.display_name,
                sink_name=None,
                stream_id=selection.stream_id,
                label=selection.label or stream.display_name,
            )
        sink = self._sink_resolver(selection.selected_input or None, selection.source)
        return AudioInputDescriptor(
            source=selection.source,
            source_path=sink,
            sink_name=sink,
            stream_id=None,
            label=selection.label or sink,
        )

    def acquire(
        self,
        selection: AudioInputSelection,
        *,
        status_callback: Optional[RouteStatusCallback] = None,
    ) -> AudioInputLease:
        if selection.source != AudioSource.APPLICATION.value:
            descriptor = self.describe(selection)
            return AudioInputLease(descriptor, descriptor.sink_name)

        assert selection.stream_id is not None
        descriptor = self.describe(selection)
        route = self._router.isolate_stream(
            selection.stream_id,
            status_callback=status_callback,
        )
        routed_descriptor = AudioInputDescriptor(
            source=descriptor.source,
            source_path=descriptor.source_path,
            sink_name=route.monitor_name,
            stream_id=descriptor.stream_id,
            label=descriptor.label,
        )
        return AudioInputLease(routed_descriptor, route.monitor_name, route)
