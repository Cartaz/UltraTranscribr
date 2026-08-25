"""Pure audio diagnostics formatting from application-owned snapshots."""
from __future__ import annotations

from typing import Any, Protocol

from config.settings import AudioSource


class _MeetingSnapshotProvider(Protocol):
    def snapshot(self) -> dict[str, Any]: ...


class AudioDiagnosticsSource(Protocol):
    """Narrow read-only application view required by diagnostics."""

    @property
    def meeting(self) -> _MeetingSnapshotProvider: ...

    def audio_discovery_snapshot(self) -> dict[str, list[dict[str, Any]]]: ...

    def list_live_sessions(
        self,
        *,
        include_text: bool = False,
    ) -> list[dict[str, Any]]: ...


def build_audio_diagnostics(source: AudioDiagnosticsSource) -> str:
    """Build a deterministic report without performing hardware/process I/O."""
    discovery = source.audio_discovery_snapshot()
    devices = [dict(item) for item in discovery.get("devices", [])]
    streams = [dict(item) for item in discovery.get("streams", [])]
    sessions = source.list_live_sessions(include_text=False)
    meeting = source.meeting.snapshot()

    lines = [
        "=== cached audio discovery ===",
        "  snapshot only; no hardware probe is started by diagnostics",
        "",
        "=== input devices ===",
    ]
    if not devices:
        lines.append("  nessun input nella cache")
    for device in devices:
        role = "monitor" if device.get("is_monitor") else "microphone"
        lines.append(
            f"  [{device.get('id', '-')}] {device.get('name') or 'input'} "
            f"role={role} channels={device.get('channels', '-')} "
            f"rate={device.get('samplerate', '-')}"
        )

    lines.extend(["", "=== playback streams ==="])
    if not streams:
        lines.append("  nessuno stream attivo nella cache")
    for stream in streams:
        lines.extend(
            [
                f"  [#{stream.get('id', '-')}] {stream.get('display_name') or 'stream'}",
                (
                    f"      pid={stream.get('process_id') or '-'} "
                    f"binary={stream.get('process_binary') or '-'} "
                    f"sink={stream.get('sink_name') or '-'} "
                    f"state={stream.get('state') or '-'}"
                ),
            ]
        )

    lines.extend(["", "=== UltraTranscribr live routing ==="])
    if not sessions:
        lines.append("  nessuna sessione Live")
    for session in sessions:
        if session.get("source") == AudioSource.APPLICATION.value:
            routing = "restored" if session.get("terminal") else "isolated"
        else:
            routing = "direct"
        lines.extend(
            [
                (
                    f"  [{session.get('id', '-')}] source={session.get('source') or '-'} "
                    f"status={session.get('status') or '-'} routing={routing}"
                ),
                (
                    f"      input={session.get('source_path') or '-'} "
                    f"capture={session.get('sink') or '-'} "
                    f"buffer={session.get('buffer_level', 0)}% "
                    f"queue_wait={session.get('queue_wait_ms', 0)}ms"
                ),
            ]
        )

    lines.extend(["", "=== meeting ==="])
    lines.append(f"  {meeting if meeting else 'nessuna riunione runtime'}")
    return "\n".join(lines)
