"""Progressive, bounded-memory file transcription worker."""
from __future__ import annotations

import copy
import logging
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from config.constants import ProcessDefaults, SYCLDefaults
from config.settings import Settings
from core.boundary_recovery import recover_boundary
from core.event_bus import EventBus
from core.models import StatusEnum
from core.text_dedup import deduplicate_text, remove_chunk_overlap
from core.transcript_export import normalize_segments
from core.transcript_quality import quality_issues
from core.word_timing import lexical_words, segment_interval
from core.whisper_backend import WhisperBackend

logger = logging.getLogger(__name__)
DEMUCS_END = 48
EventSink = Callable[[str, Any], None]


class FileTranscriberThread(threading.Thread):
    def __init__(
        self,
        file_path: str,
        backend: WhisperBackend,
        settings: Settings,
        song_mode: bool = False,
        isolate_vocals_flag: bool = False,
        language: Optional[str] = None,
        *,
        event_sink: Optional[EventSink] = None,
        thread_name: str = "FileTranscriberThread",
    ) -> None:
        super().__init__(daemon=True, name=thread_name)
        self._file_path = file_path
        self._backend = backend
        self._settings = settings
        self._language = language or settings.language
        self._song_mode = bool(song_mode)
        self._isolate_vocals = bool(isolate_vocals_flag)
        self._event_sink = event_sink
        self._stop_event = threading.Event()
        self._vocal_path: Optional[str] = None
        self._pcm_wav_path: Optional[str] = None
        self._terminal_state: str | None = None
        self._conversion_process: Optional[subprocess.Popen[bytes]] = None
        self._conversion_lock = threading.Lock()
        # Trial-only switch; the installed default remains unchanged until the
        # complete application and independent evaluation have passed.
        self._boundary_recovery = os.environ.get(
            "ULTRATRANSCRIBR_EXPERIMENTAL_BOUNDARY_RECOVERY"
        ) == "1" and not self._song_mode

    def _emit(self, event: str, payload: Any = None) -> None:
        if self._event_sink is not None:
            self._event_sink(event, payload)
        else:
            EventBus().emit(event, payload)

    def stop(self) -> None:
        self._stop_event.set()
        with self._conversion_lock:
            proc = self._conversion_process
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
            except OSError:
                pass

    def run(self) -> None:
        try:
            source = self._file_path
            if self._isolate_vocals and self._song_mode:
                source = self._run_vocal_isolation()
                if self._stop_event.is_set():
                    return
            self._emit("file_transcriber_status_changed", StatusEnum.RUNNING.value)
            start_pct = DEMUCS_END if self._vocal_path else 0
            self._emit("file_transcriber_progress", start_pct)
            self._transcribe_progressively(source, start_pct)
            if not self._stop_event.is_set():
                self._terminal_state = StatusEnum.COMPLETED.value
                self._emit("file_transcriber_status_changed", self._terminal_state)
                self._emit("file_transcriber_completed", None)
        except Exception as exc:
            if not self._stop_event.is_set():
                self._terminal_state = StatusEnum.ERROR.value
                logger.exception("Errore trascrizione file")
                self._emit("file_transcriber_error", f"Errore trascrizione: {exc}")
                self._emit("file_transcriber_status_changed", self._terminal_state)
        finally:
            if self._stop_event.is_set() and self._terminal_state is None:
                self._emit("file_transcriber_status_changed", StatusEnum.STOPPED.value)
            self._cleanup()

    def _run_vocal_isolation(self) -> str:
        from core.vocal_isolator import isolate_vocals

        self._emit("file_transcriber_status_changed", StatusEnum.ISOLATING_VOCALS.value)

        def progress(value: int) -> None:
            self._emit("file_transcriber_progress", min(DEMUCS_END, max(0, value)))

        self._vocal_path = isolate_vocals(
            self._file_path,
            model_name="htdemucs",
            stop_event=self._stop_event,
            progress_callback=progress,
        )
        return self._vocal_path

    def _transcribe_progressively(self, source: str, start_pct: int) -> None:
        wav_path = self._convert_to_pcm_wav(source)
        if self._stop_event.is_set():
            return
        self._pcm_wav_path = wav_path
        full_parts: list[str] = []
        previous = ""
        last_segment_end_s = 0.0
        decoder_previous = ""
        decoder_cutoff = 0.0
        boundary_history: list[dict[str, Any]] = []
        chunk_frames = int(ProcessDefaults.FILE_SEGMENT_LENGTH_S * 16000)
        overlap_frames = int(ProcessDefaults.FILE_OVERLAP_DURATION_S * 16000)
        step = max(1, chunk_frames - overlap_frames)
        with wave.open(wav_path, "rb") as wf:
            if (
                wf.getnchannels() != 1
                or wf.getframerate() != 16000
                or wf.getsampwidth() != 2
            ):
                raise RuntimeError("WAV normalizzato non è PCM16 mono 16 kHz")
            total = wf.getnframes()
            if total <= 0:
                raise RuntimeError("File audio vuoto")
            offset = 0
            while offset < total and not self._stop_event.is_set():
                wf.setpos(offset)
                raw = wf.readframes(min(chunk_frames, total - offset))
                if not raw:
                    break
                text, raw_segments = self._request_checked_chunk(
                    raw, (decoder_previous if self._boundary_recovery else previous)[-500:] or None,
                    offset / 16000.0,
                )
                # Preserve evidence of unresolved loops. Deleting them here
                # would make the plain text disagree with the timed source.
                if self._song_mode:
                    text = deduplicate_text(text, preserve_repetitions=True)
                chunk_offset_s = offset / 16000.0
                if self._boundary_recovery:
                    # Reconstruct the unmodified decoder context independently
                    # of recovered text, as in the validated prototype.
                    baseline = self._normalize_chunk_segments(
                        raw_segments, chunk_offset_s=chunk_offset_s,
                        committed_before_s=decoder_cutoff,
                    )
                    def compact_text(value):
                        return "".join(value.split())
                    if raw_segments and compact_text(text) == compact_text(
                        " ".join(str(s.get("text") or "") for s in raw_segments)
                    ):
                        decoder_text = " ".join(s["text"] for s in baseline)
                    else:
                        decoder_text = remove_chunk_overlap(decoder_previous, text)
                    if decoder_text:
                        decoder_previous = (decoder_previous + " " + decoder_text).strip()
                    if baseline:
                        decoder_cutoff = max(decoder_cutoff, max(s["end"] for s in baseline))
                    recovered = recover_boundary(
                        raw_segments, boundary_history, chunk_offset_s, last_segment_end_s
                    )
                else:
                    recovered = []
                segments = self._normalize_chunk_segments(
                    recovered + raw_segments,
                    chunk_offset_s=chunk_offset_s,
                    committed_before_s=last_segment_end_s,
                )

                def compact(value):
                    return "".join(value.split())

                if raw_segments and compact(text) == compact(
                    " ".join(str(s.get("text") or "") for s in raw_segments)
                ):
                    # Timing, rather than a matching phrase alone, establishes
                    # overlap. An authentic repeated sentence in a later
                    # window must not be deleted just because it is identical.
                    text = " ".join(segment["text"] for segment in segments)
                else:
                    text = remove_chunk_overlap(previous, text)
                if text:
                    full_parts.append(text)
                    previous = (previous + " " + text).strip()
                    self._emit("file_transcriber_new_text", text)
                    self._emit("file_transcriber_full_text", "\n".join(full_parts))
                if segments:
                    last_segment_end_s = max(
                        last_segment_end_s,
                        max(float(segment["end"]) for segment in segments),
                    )
                    if self._boundary_recovery:
                        boundary_history.extend(copy.deepcopy(segments))
                        floor = max(s["end"] for s in segments) - 60.0
                        boundary_history = [s for s in boundary_history if s["end"] >= floor]
                    self._emit("file_transcriber_segments", segments)
                    notices = []
                    for segment in segments:
                        evidence = segment.get("quality_recovery") or {}
                        if evidence.get("reason") == "overlap_boundary_recovered":
                            notices.append({
                                "reason": "overlap_boundary_recovered",
                                "start": evidence["original_audio_start"],
                                "end": evidence["original_audio_end"],
                                "recovered": False,
                                "timing_requires_review": True,
                            })
                    if notices:
                        self._emit("file_transcriber_quality", notices)

                consumed = min(total, offset + len(raw) // 2)
                frac = consumed / total
                pct = start_pct + int(frac * (100 - start_pct))
                self._emit(
                    "file_transcriber_progress",
                    min(99, pct) if consumed < total else 100,
                )
                if consumed >= total:
                    break
                offset += step
        if not self._stop_event.is_set():
            self._emit("file_transcriber_progress", 100)

    def _request_chunk(self, wav_bytes: bytes, prompt: Optional[str]) -> str:
        """Backward-compatible plain-text request used by existing callers/tests."""
        last: Exception | None = None
        for attempt in range(3):
            if self._stop_event.is_set():
                return ""
            try:
                result = self._backend.transcribe_audio(
                    wav_bytes,
                    language=self._language,
                    prompt=prompt,
                    verbose=False,
                    timeout=SYCLDefaults.FILE_CHUNK_REQUEST_TIMEOUT_S,
                    vad=False if self._song_mode else self._settings.vad_filter,
                )
                return result if isinstance(result, str) else str(result.get("text", ""))
            except RuntimeError as exc:
                last = exc
                if getattr(self._backend, "is_running", True) is False:
                    break
                if attempt < 2:
                    self._stop_event.wait(ProcessDefaults.TRANSCRIBE_RETRY_DELAY_S)
                    if getattr(self._backend, "is_running", True) is False:
                        break
        raise RuntimeError(f"chunk file fallito dopo 3 tentativi: {last}")

    def _request_chunk_verbose(
        self,
        wav_bytes: bytes,
        prompt: Optional[str],
    ) -> tuple[str, list[dict[str, Any]]]:
        last: Exception | None = None
        for attempt in range(3):
            if self._stop_event.is_set():
                return "", []
            try:
                result = self._backend.transcribe_audio(
                    wav_bytes,
                    language=self._language,
                    prompt=prompt,
                    verbose=True,
                    timeout=SYCLDefaults.FILE_CHUNK_REQUEST_TIMEOUT_S,
                    vad=False if self._song_mode else self._settings.vad_filter,
                )
                if isinstance(result, str):
                    return result, []
                text = str(result.get("text", ""))
                segments = result.get("segments", [])
                return text, [s for s in segments if isinstance(s, dict)] if isinstance(
                    segments, list
                ) else []
            except RuntimeError as exc:
                last = exc
                if getattr(self._backend, "is_running", True) is False:
                    break
                if attempt < 2:
                    self._stop_event.wait(ProcessDefaults.TRANSCRIBE_RETRY_DELAY_S)
                    if getattr(self._backend, "is_running", True) is False:
                        break
        raise RuntimeError(f"chunk file fallito dopo 3 tentativi: {last}")

    @classmethod
    def _normalize_chunk_segments(
        cls,
        raw_segments: list[dict[str, Any]],
        *,
        chunk_offset_s: float,
        committed_before_s: float,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        cutoff = max(0.0, float(committed_before_s))
        for raw in raw_segments:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text") or "").strip()
            if not text:
                continue
            timing = cls._segment_time_seconds(raw)
            if timing is None:
                continue
            local_start, local_end = timing
            start = max(0.0, float(chunk_offset_s) + local_start)
            end = max(start, float(chunk_offset_s) + local_end)
            if end <= cutoff + 0.001:
                continue
            raw_words = raw.get("words")
            if start < cutoff:
                whole, _warnings = lexical_words(text, raw_words or [])
                if whole:
                    kept = [
                        word
                        for word in whole
                        if chunk_offset_s + word["end"] > cutoff + 0.001
                    ]
                    if not kept:
                        continue
                    text = "".join(word["word"] for word in kept).strip()
                    raw_words = kept
                start = cutoff
            item: dict[str, Any] = {"start": start, "end": end, "text": text}
            words = cls._normalize_chunk_words(
                raw_words,
                chunk_offset_s=chunk_offset_s,
                committed_before_s=cutoff,
                segment_start=start,
                segment_end=end,
            )
            if words:
                item["words"] = words
            if "quality_issues" in raw:
                item["quality_issues"] = [
                    {
                        **issue,
                        **{
                            key: float(chunk_offset_s) + float(issue[key])
                            for key in ("start", "end")
                            if key in issue
                        },
                    }
                    for issue in raw["quality_issues"]
                ]
            if "quality_recovery" in raw:
                item["quality_recovery"] = raw["quality_recovery"]
            result.append(item)
        return normalize_segments(result)

    @staticmethod
    def _normalize_chunk_words(
        raw_words: Any,
        *,
        chunk_offset_s: float,
        committed_before_s: float,
        segment_start: float,
        segment_end: float,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_words, list):
            return []
        words: list[dict[str, Any]] = []
        for raw in raw_words:
            if not isinstance(raw, dict):
                continue
            word = str(raw.get("word") or "")
            if not word.strip():
                continue
            try:
                start = float(chunk_offset_s) + float(raw.get("start", 0.0))
                end = float(chunk_offset_s) + float(raw.get("end", raw.get("start", 0.0)))
            except (TypeError, ValueError):
                continue
            if end <= committed_before_s + 0.001:
                continue
            start = max(segment_start, committed_before_s, start)
            end = min(segment_end, max(start, end))
            if start > segment_end:
                continue
            item: dict[str, Any] = {
                "word": word,
                "start": start,
                "end": max(start, end),
            }
            try:
                probability = float(raw.get("probability"))
            except (TypeError, ValueError):
                probability = None
            if probability is not None:
                item["probability"] = probability
            words.append(item)
        words.sort(key=lambda item: item["start"])
        return words

    @staticmethod
    def _segment_time_seconds(raw: dict[str, Any]) -> tuple[float, float] | None:
        return segment_interval(raw)

    def _convert_to_pcm_wav(self, source: str) -> str:
        if not shutil.which("ffmpeg"):
            return self._convert_with_soundfile(source)
        tmp = tempfile.mkdtemp(prefix="ultratranscribr_pcm_")
        out = os.path.join(tmp, "audio.wav")
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            source,
            "-vn",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            "-hide_banner",
            "-loglevel",
            "error",
            out,
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        with self._conversion_lock:
            self._conversion_process = proc
        try:
            while proc.poll() is None:
                if self._stop_event.wait(0.1):
                    try:
                        proc.terminate()
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2.0)
                    shutil.rmtree(tmp, ignore_errors=True)
                    raise RuntimeError("conversione audio interrotta")
            stderr = proc.stderr.read() if proc.stderr is not None else b""
            if proc.returncode != 0:
                shutil.rmtree(tmp, ignore_errors=True)
                detail = stderr.decode("utf-8", errors="replace")[-800:]
                raise RuntimeError(f"ffmpeg conversion fallita: {detail}")
            return out
        finally:
            with self._conversion_lock:
                if self._conversion_process is proc:
                    self._conversion_process = None
            if proc.stderr is not None:
                proc.stderr.close()

    def _convert_with_soundfile(self, source: str) -> str:
        import soundfile as sf

        from core.audio_resampler import resample

        data, sr = sf.read(source, dtype="float32", always_2d=True)
        if self._stop_event.is_set():
            raise RuntimeError("conversione audio interrotta")
        mono = data.mean(axis=1, dtype=np.float32)
        mono = resample(mono, int(sr), 16000) if int(sr) != 16000 else mono
        tmp = tempfile.mkdtemp(prefix="ultratranscribr_pcm_")
        out = os.path.join(tmp, "audio.wav")
        sf.write(out, mono, 16000, subtype="PCM_16")
        return out

    @staticmethod
    def _wrap_pcm16(raw: bytes) -> bytes:
        return struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + len(raw),
            b"WAVE",
            b"fmt ",
            16,
            1,
            1,
            16000,
            32000,
            2,
            16,
            b"data",
            len(raw),
        ) + raw

    def _cleanup(self) -> None:
        if self._vocal_path:
            try:
                from core.vocal_isolator import cleanup_vocals

                cleanup_vocals(self._vocal_path)
            except Exception:
                logger.debug("Cleanup vocals fallito", exc_info=True)
            self._vocal_path = None
        if self._pcm_wav_path:
            shutil.rmtree(str(Path(self._pcm_wav_path).parent), ignore_errors=True)
            self._pcm_wav_path = None


    def _request_checked_chunk(self, pcm16, prompt, offset_s):
        text, segments = self._request_chunk_verbose(self._wrap_pcm16(pcm16), prompt)
        if self._song_mode or self._stop_event.is_set():
            return text, segments
        initial = quality_issues(text, segments, pcm16)
        if not initial:
            return text, segments
        original = {"text": text, "segments": segments}
        duration = len(pcm16) / 32000
        recovered_segments = []
        recovered_parts = []
        recovery_complete = True
        # One bounded recovery pass, with independent short windows and no
        # previous-text prompt to propagate the failed decoder context.
        window_frames = 12 * 16000
        context_frames = 16000
        total_frames = len(pcm16) // 2
        try:
            for position in range(0, total_frames, window_frames):
                if self._stop_event.is_set():
                    return text, segments
                lo = max(0, position - context_frames)
                hi = min(total_frames, position + window_frames)
                part_text, part_segments = self._request_chunk_verbose(
                    self._wrap_pcm16(pcm16[lo * 2 : hi * 2]), None
                )
                if part_segments and "".join(part_text.split()) != "".join(
                    "".join(str(s.get("text") or "").split()) for s in part_segments
                ):
                    recovery_complete = False
                shifted = self._normalize_chunk_segments(
                    part_segments,
                    chunk_offset_s=lo / 16000,
                    committed_before_s=max(
                        (s["end"] for s in recovered_segments), default=0
                    ),
                )
                recovered_segments.extend(shifted)
                recovered_parts.append(part_text)
        except RuntimeError:
            recovery_complete = False
            # Network/decoder failure in recovery must not erase the first
            # usable response or lose the location requiring manual review.
            logger.exception(
                "Recupero del tratto %.2f–%.2f non riuscito", offset_s, offset_s + duration
            )
        recovered_text = " ".join(segment["text"] for segment in recovered_segments).strip()
        remaining = quality_issues(recovered_text, recovered_segments, pcm16)

        def uncovered(issues):
            return sum(
                float(i.get("end", 0)) - float(i.get("start", 0))
                for i in issues
                if i["reason"] == "uncovered_audio"
            )

        accepted = (
            recovery_complete
            and bool(recovered_text and recovered_segments)
            and len(remaining) < len(initial)
            and uncovered(remaining) <= uncovered(initial) + 0.5
        )
        if accepted:
            text, segments = recovered_text, recovered_segments
        else:
            remaining = initial
        payload = [
            {
                **issue,
                "start": offset_s + float(issue.get("start", 0)),
                "end": offset_s + float(issue.get("end", duration)),
                "recovered": accepted and not remaining,
            }
            for issue in (remaining or initial)
        ]
        self._emit("file_transcriber_quality", payload)
        logger.warning(
            "Qualità trascrizione %.2f–%.2f: %s; recupero=%s",
            offset_s,
            offset_s + duration,
            ", ".join(sorted({issue["reason"] for issue in initial})),
            accepted,
        )
        if segments:
            segments = [dict(s) for s in segments]
            segments[0]["quality_recovery"] = {
                "attempted": True,
                "accepted": accepted,
                "chunk_start_s": offset_s,
                "original": original,
                "candidate": {
                    "text": recovered_text,
                    "responses": recovered_parts,
                    "segments": recovered_segments,
                },
            }
            if remaining:
                segments[0]["quality_issues"] = remaining
        return text, segments
