"""Multi-source Meeting acquisition and canonical recording preparation.

Meeting analysis consumes exactly one canonical mono 16 kHz FLAC.  Realtime
capture may have several independent inputs: each source is retained as its own
track and the tracks are time-aligned into the canonical recording.  Imported
media is normalized directly to the same canonical representation.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import soundfile as sf

from config.constants import AppMeta, ProcessDefaults
from config.settings import Settings
from core.audio_capture import AudioCaptureThread
from core.audio_inputs import AudioInputLease, AudioInputResolver, AudioInputSelection
from core.audio_resampler import resample
from core.microphone_recording import MicrophoneRecorder, RecordingInfo

logger = logging.getLogger(__name__)
CaptureEventSink = Callable[[str, Any], None]


class _RecordingOnlyBuffer:
    buffer_level = 0

    def put(self, _chunk: Any) -> None:
        return

    def close_input(self) -> None:
        return

    def close(self) -> None:
        return


@dataclass
class MeetingTrack:
    index: int
    selection: AudioInputSelection
    lease: AudioInputLease
    recorder: MicrophoneRecorder
    capture: AudioCaptureThread
    first_sample_monotonic: Optional[float] = None

    @property
    def id(self) -> str:
        return f"source-{self.index + 1}"


@dataclass(frozen=True)
class MeetingRecordingBundle:
    recording: RecordingInfo
    sources: list[dict[str, Any]]


class MeetingCaptureSession:
    """Own all native resources for one realtime Meeting acquisition."""

    _CAPTURE_JOIN_TIMEOUT_S = 5.0

    def __init__(
        self,
        session_id: str,
        settings: Settings,
        resolver: AudioInputResolver,
        *,
        event_sink: Optional[CaptureEventSink] = None,
    ) -> None:
        self.session_id = str(session_id)
        self.settings = settings
        self._resolver = resolver
        self._event_sink = event_sink
        self._tracks: list[MeetingTrack] = []
        self._lock = threading.RLock()
        self._closed = False

    @property
    def tracks(self) -> tuple[MeetingTrack, ...]:
        with self._lock:
            return tuple(self._tracks)

    @property
    def duration_s(self) -> float:
        with self._lock:
            return max((track.recorder.duration_s for track in self._tracks), default=0.0)

    def start(self, selections: list[AudioInputSelection]) -> None:
        if not selections:
            raise ValueError("Aggiungi almeno una sorgente alla riunione")
        with self._lock:
            if self._closed or self._tracks:
                raise RuntimeError("acquisizione riunione già avviata")

        created: list[MeetingTrack] = []
        try:
            for index, selection in enumerate(selections):
                lease = self._resolver.acquire(
                    selection,
                    status_callback=lambda payload, idx=index: self._route_event(idx, payload),
                )
                recorder = MicrophoneRecorder(f"{self.session_id}-source-{index + 1}")
                recorder.start()
                track_ref: list[MeetingTrack] = []

                def write(samples: np.ndarray, ref: list[MeetingTrack] = track_ref) -> None:
                    if not ref:
                        return
                    track = ref[0]
                    if track.first_sample_monotonic is None:
                        track.first_sample_monotonic = time.monotonic()
                    track.recorder.write(samples)

                capture = AudioCaptureThread(
                    _RecordingOnlyBuffer(),
                    self.settings.with_(audio_source=selection.source),
                    lease.capture_sink,
                    selection.source,
                    session_id=f"meeting-{self.session_id}-{index + 1}",
                    event_sink=lambda event, payload, idx=index: self._capture_event(idx, event, payload),
                    sample_sink=write,
                )
                track = MeetingTrack(
                    index=index,
                    selection=selection,
                    lease=lease,
                    recorder=recorder,
                    capture=capture,
                )
                track_ref.append(track)
                created.append(track)
                capture.start()
            with self._lock:
                self._tracks = created
        except Exception:
            self._cleanup_created(created, abandon=True)
            raise

    def stop_and_finalize(self) -> MeetingRecordingBundle:
        with self._lock:
            if self._closed:
                raise RuntimeError("acquisizione riunione già chiusa")
            tracks = list(self._tracks)
        if not tracks:
            raise RuntimeError("nessuna sorgente riunione attiva")

        for track in tracks:
            track.capture.stop()
        for track in tracks:
            if track.capture.is_alive() and track.capture is not threading.current_thread():
                track.capture.join(timeout=self._CAPTURE_JOIN_TIMEOUT_S)
        alive = [track.id for track in tracks if track.capture.is_alive()]
        if alive:
            raise RuntimeError(
                "Le sorgenti audio non si sono arrestate in tempo: " + ", ".join(alive)
            )

        for track in tracks:
            try:
                track.lease.close()
            except Exception:
                logger.exception("Ripristino route Meeting fallito per %s", track.id)

        infos: list[tuple[MeetingTrack, RecordingInfo]] = []
        for track in tracks:
            info = track.recorder.finalize()
            if info is not None:
                infos.append((track, info))
        if not infos:
            raise RuntimeError("Registrazione riunione vuota")

        first_times = [
            track.first_sample_monotonic
            for track, _ in infos
            if track.first_sample_monotonic is not None
        ]
        anchor = min(first_times) if first_times else None
        source_records: list[dict[str, Any]] = []
        mix_inputs: list[tuple[RecordingInfo, float]] = []
        for track, info in infos:
            offset = 0.0
            if anchor is not None and track.first_sample_monotonic is not None:
                offset = max(0.0, track.first_sample_monotonic - anchor)
            descriptor = track.lease.descriptor
            source_records.append(
                {
                    "id": track.id,
                    **descriptor.to_dict(),
                    "offset_s": round(offset, 3),
                    "recording": info.to_dict(),
                }
            )
            mix_inputs.append((info, offset))

        canonical = mix_recordings(
            mix_inputs,
            AppMeta.RECORDINGS_DIR / f"{self.session_id}.flac",
        )
        with self._lock:
            self._closed = True
        return MeetingRecordingBundle(recording=canonical, sources=source_records)

    def abandon(self) -> None:
        with self._lock:
            if self._closed:
                return
            tracks = list(self._tracks)
            self._closed = True
        for track in tracks:
            try:
                track.capture.stop()
            except Exception:
                logger.exception("Stop capture Meeting fallito per %s", track.id)
            try:
                track.lease.close()
            except Exception:
                logger.exception("Ripristino route Meeting fallito per %s", track.id)
            try:
                track.recorder.abandon()
            except Exception:
                logger.exception("Abbandono recording Meeting fallito per %s", track.id)

    def _cleanup_created(self, tracks: list[MeetingTrack], *, abandon: bool) -> None:
        for track in reversed(tracks):
            try:
                track.capture.stop()
                if track.capture.is_alive() and track.capture is not threading.current_thread():
                    track.capture.join(timeout=self._CAPTURE_JOIN_TIMEOUT_S)
            except Exception:
                logger.exception("Cleanup capture Meeting fallito")
            try:
                track.lease.close()
            except Exception:
                logger.exception("Cleanup route Meeting fallito")
            try:
                if abandon:
                    track.recorder.abandon()
                else:
                    track.recorder.finalize()
            except Exception:
                logger.exception("Cleanup recorder Meeting fallito")

    def _capture_event(self, index: int, event: str, payload: Any) -> None:
        if self._event_sink is not None:
            self._event_sink(
                event,
                {"source_index": index, "payload": payload},
            )

    def _route_event(self, index: int, payload: dict[str, Any]) -> None:
        if self._event_sink is not None:
            self._event_sink(
                "route_status",
                {"source_index": index, **dict(payload or {})},
            )


def recording_info(path: Path | str) -> RecordingInfo:
    target = Path(path)
    stat = target.stat()
    info = sf.info(str(target))
    if not info.samplerate:
        raise RuntimeError("sample rate registrazione non disponibile")
    return RecordingInfo(
        path=str(target),
        duration_s=float(info.frames) / float(info.samplerate),
        size_bytes=stat.st_size,
        sample_rate=int(info.samplerate),
        channels=int(info.channels),
        format="flac",
    )


def normalize_media_to_flac(
    source: Path | str,
    target: Path | str,
    *,
    stop_event: Optional[threading.Event] = None,
) -> RecordingInfo:
    """Normalize arbitrary media to the Meeting canonical audio format."""
    src = Path(source).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"file riunione non trovato: {src}")
    dst = Path(target).expanduser()
    dst.parent.mkdir(parents=True, exist_ok=True)
    temp = dst.with_suffix(".flac.tmp")
    temp.unlink(missing_ok=True)
    cancel = stop_event or threading.Event()

    if shutil.which("ffmpeg"):
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-vn",
            "-ar",
            str(ProcessDefaults.SAMPLE_RATE),
            "-ac",
            "1",
            "-c:a",
            "flac",
            "-hide_banner",
            "-loglevel",
            "error",
            str(temp),
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            while proc.poll() is None:
                if cancel.wait(0.1):
                    proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2.0)
                    temp.unlink(missing_ok=True)
                    raise RuntimeError("import riunione interrotto")
            stderr = proc.stderr.read() if proc.stderr is not None else b""
            if proc.returncode != 0:
                detail = stderr.decode("utf-8", errors="replace")[-800:]
                temp.unlink(missing_ok=True)
                raise RuntimeError(f"conversione riunione fallita: {detail}")
        finally:
            if proc.stderr is not None:
                proc.stderr.close()
    else:
        data, sample_rate = sf.read(str(src), dtype="float32", always_2d=True)
        if cancel.is_set():
            raise RuntimeError("import riunione interrotto")
        if data.size == 0:
            raise RuntimeError("file riunione vuoto")
        mono = data.mean(axis=1, dtype=np.float32)
        if int(sample_rate) != ProcessDefaults.SAMPLE_RATE:
            mono = resample(mono, int(sample_rate), ProcessDefaults.SAMPLE_RATE)
        if cancel.is_set():
            raise RuntimeError("import riunione interrotto")
        sf.write(
            str(temp),
            mono,
            ProcessDefaults.SAMPLE_RATE,
            subtype="PCM_16",
            format="FLAC",
        )

    os.replace(temp, dst)
    result = recording_info(dst)
    if result.duration_s <= 0:
        dst.unlink(missing_ok=True)
        raise RuntimeError("file riunione vuoto")
    return result


def mix_recordings(
    sources: list[tuple[RecordingInfo, float]],
    target: Path | str,
) -> RecordingInfo:
    """Time-align mono tracks and stream a bounded-memory canonical FLAC mix."""
    if not sources:
        raise ValueError("nessuna traccia da mixare")
    dst = Path(target)
    dst.parent.mkdir(parents=True, exist_ok=True)
    temp = dst.with_suffix(".flac.tmp")
    temp.unlink(missing_ok=True)

    handles: list[tuple[sf.SoundFile, int]] = []
    try:
        for info, offset_s in sources:
            handle = sf.SoundFile(info.path, mode="r")
            if handle.samplerate != ProcessDefaults.SAMPLE_RATE or handle.channels != 1:
                handle.close()
                raise RuntimeError("traccia Meeting non normalizzata a mono 16 kHz")
            offset_frames = max(0, int(round(float(offset_s) * handle.samplerate)))
            handles.append((handle, offset_frames))
        total_frames = max(offset + len(handle) for handle, offset in handles)
        if total_frames <= 0:
            raise RuntimeError("registrazione riunione vuota")

        block_size = 65536
        with sf.SoundFile(
            str(temp),
            mode="w",
            samplerate=ProcessDefaults.SAMPLE_RATE,
            channels=1,
            subtype="PCM_16",
            format="FLAC",
        ) as output:
            output_pos = 0
            while output_pos < total_frames:
                count = min(block_size, total_frames - output_pos)
                mixed = np.zeros(count, dtype=np.float32)
                contributors = np.zeros(count, dtype=np.float32)
                for handle, offset in handles:
                    local_start = output_pos - offset
                    read_start = max(0, local_start)
                    output_start = max(0, -local_start)
                    available = min(count - output_start, len(handle) - read_start)
                    if available <= 0:
                        continue
                    handle.seek(read_start)
                    data = handle.read(available, dtype="float32", always_2d=False)
                    actual = len(data)
                    if actual <= 0:
                        continue
                    end = output_start + actual
                    mixed[output_start:end] += np.asarray(data, dtype=np.float32)
                    contributors[output_start:end] += 1.0
                mask = contributors > 0
                mixed[mask] /= contributors[mask]
                output.write(np.clip(mixed, -1.0, 1.0))
                output_pos += count
        os.replace(temp, dst)
        return recording_info(dst)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    finally:
        for handle, _offset in handles:
            handle.close()
