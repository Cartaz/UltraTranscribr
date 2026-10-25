"""Crash-resistant shared microphone recording for Live and Meeting sessions."""
from __future__ import annotations

import fcntl
import logging
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from config.constants import AppMeta, ProcessDefaults

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecordingInfo:
    path: str
    duration_s: float
    size_bytes: int
    sample_rate: int = ProcessDefaults.SAMPLE_RATE
    channels: int = 1
    format: str = "flac"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MicrophoneRecorder:
    """Append PCM16 journal first, finalize losslessly to FLAC on close.

    The append-only `.pcm.part` file remains useful after an unexpected process
    exit. Normal shutdown streams it to FLAC without loading the whole recording
    into memory.
    """

    def __init__(
        self,
        session_id: str,
        *,
        root: Optional[Path] = None,
        sample_rate: int = ProcessDefaults.SAMPLE_RATE,
    ) -> None:
        self.session_id = str(session_id)
        self.root = Path(root or AppMeta.RECORDINGS_DIR)
        self.sample_rate = int(sample_rate)
        self.part_path = self.root / f"{self.session_id}.pcm.part"
        self.final_path = self.root / f"{self.session_id}.flac"
        self._handle = None
        self._journal_lock = None
        self._lock = threading.RLock()
        self._samples = 0
        self._samples_since_sync = 0
        self._closed = False

    @property
    def duration_s(self) -> float:
        with self._lock:
            return self._samples / float(self.sample_rate)

    def start(self) -> None:
        with self._lock:
            if self._handle is not None:
                return
            if self._closed:
                raise RuntimeError("registrazione già chiusa")
            self.root.mkdir(parents=True, exist_ok=True)
            journal_lock = self._lock_journal(self.part_path)
            try:
                self._handle = open(self.part_path, "ab", buffering=0)
            except Exception:
                journal_lock.close()
                raise
            self._journal_lock = journal_lock
            try:
                self._samples = self.part_path.stat().st_size // 2
            except OSError:
                self._samples = 0

    def write(self, samples: np.ndarray) -> None:
        data = np.asarray(samples, dtype=np.float32).reshape(-1)
        if not data.size:
            return
        pcm = np.clip(data, -1.0, 1.0)
        pcm = np.rint(pcm * 32767.0).astype("<i2", copy=False)
        payload = pcm.tobytes()
        with self._lock:
            if self._closed:
                return
            if self._handle is None:
                self.start()
            assert self._handle is not None
            self._handle.write(payload)
            count = len(payload) // 2
            self._samples += count
            self._samples_since_sync += count
            # Persist roughly every five seconds without fsyncing every 64 ms
            # PortAudio block.
            if self._samples_since_sync >= self.sample_rate * 5:
                self._sync_locked()

    def checkpoint(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._sync_locked()

    def finalize(self) -> Optional[RecordingInfo]:
        with self._lock:
            if self._closed:
                if self.final_path.is_file():
                    return self._info_from_final()
                return None
            if self._handle is None:
                self.start()
            if self._handle is not None:
                self._sync_locked()
                self._handle.close()
                self._handle = None
            self._closed = True
            samples = self._samples
            journal_lock = self._journal_lock
            self._journal_lock = None

        try:
            if samples <= 0 or not self.part_path.is_file():
                self.part_path.unlink(missing_ok=True)
                return None
            return self._finalize_partial(
                self.part_path, final_path=self.final_path, sample_rate=self.sample_rate)
        finally:
            journal_lock.close()

    def abandon(self) -> None:
        """Close the journal without deleting it so it can be recovered later."""
        with self._lock:
            if self._handle is not None:
                self._sync_locked()
                self._handle.close()
                self._handle = None
            self._closed = True
            journal_lock = getattr(self, "_journal_lock", None)
            if journal_lock is not None:
                journal_lock.close()
                self._journal_lock = None

    def _sync_locked(self) -> None:
        assert self._handle is not None
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._samples_since_sync = 0

    def _info_from_final(self) -> RecordingInfo:
        stat = self.final_path.stat()
        with sf.SoundFile(str(self.final_path), "r") as audio:
            duration = len(audio) / float(audio.samplerate)
        return RecordingInfo(
            path=str(self.final_path),
            duration_s=duration,
            size_bytes=stat.st_size,
            sample_rate=self.sample_rate,
        )

    @staticmethod
    def finalize_partial(
        part_path: Path | str,
        *,
        final_path: Path | str | None = None,
        sample_rate: int = ProcessDefaults.SAMPLE_RATE,
    ) -> RecordingInfo:
        with MicrophoneRecorder._lock_journal(Path(part_path)):
            return MicrophoneRecorder._finalize_partial(
                part_path, final_path=final_path, sample_rate=sample_rate)

    @staticmethod
    def _lock_journal(part: Path):
        # Keep a separate stable lock inode: the journal itself is unlinked
        # during finalization. Recovery must never claim a live recording.
        handle = open(part.with_name("." + part.name + ".lock"), "a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            handle.close()
            raise
        return handle

    @staticmethod
    def _finalize_partial(
        part_path: Path | str,
        *,
        final_path: Path | str | None = None,
        sample_rate: int = ProcessDefaults.SAMPLE_RATE,
    ) -> RecordingInfo:
        part = Path(part_path)
        if not part.is_file():
            raise FileNotFoundError(part)
        size = part.stat().st_size
        if size < 2:
            raise RuntimeError("journal audio vuoto")
        # Ignore a trailing single byte if a process died during the final
        # sample write. PCM16 samples before it remain valid.
        usable_bytes = size - (size % 2)
        target = Path(final_path) if final_path else part.with_suffix("").with_suffix(".flac")
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".tmp")
        try:
            with sf.SoundFile(
                str(part),
                mode="r",
                samplerate=int(sample_rate),
                channels=1,
                subtype="PCM_16",
                format="RAW",
            ) as source, sf.SoundFile(
                str(temp),
                mode="w",
                samplerate=int(sample_rate),
                channels=1,
                subtype="PCM_16",
                format="FLAC",
            ) as destination:
                remaining = usable_bytes // 2
                while remaining > 0:
                    block = source.read(min(65536, remaining), dtype="float32", always_2d=False)
                    if len(block) == 0:
                        break
                    destination.write(block)
                    remaining -= len(block)
            os.replace(temp, target)
            part.unlink()
        except Exception:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        stat = target.stat()
        samples = usable_bytes // 2
        return RecordingInfo(
            path=str(target),
            duration_s=samples / float(sample_rate),
            size_bytes=stat.st_size,
            sample_rate=int(sample_rate),
        )

    @classmethod
    def recover_orphaned(cls, root: Optional[Path] = None) -> list[RecordingInfo]:
        base = Path(root or AppMeta.RECORDINGS_DIR)
        recovered: list[RecordingInfo] = []
        if not base.is_dir():
            return recovered
        for part in sorted(base.glob("*.pcm.part")):
            try:
                recovered.append(cls.finalize_partial(part))
            except (BlockingIOError, FileNotFoundError):
                # A capture still owns the journal, or another recovery won.
                continue
            except Exception:
                logger.exception("Recovery registrazione microfono fallito: %s", part)
        return recovered
