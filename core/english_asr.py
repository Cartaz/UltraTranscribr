"""Qwen ASR for the optional English meeting worker process.

The production Whisper backend remains responsible for Live and Dictation.
This backend is owned by one isolated meeting job and uses Intel XPU only.
"""

from __future__ import annotations

import gc
import hashlib
import io
import logging
import wave
from contextlib import contextmanager
from pathlib import Path
from threading import Event

from core.english_models import EnglishPipelineCancelled
from core.meeting_engine import meeting_language


logger = logging.getLogger(__name__)
MAX_NEW_TOKENS = 512
MAX_RECOVERY_SPLITS = 3
MIN_RECOVERY_WINDOW_S = 3
SPLIT_SEARCH_RADIUS_S = 2


class ASRTokenLimitError(RuntimeError):
    """A window hit the configured generation ceiling without an end token."""

    def __init__(self, tokens: int):
        self.tokens = tokens
        super().__init__(
            "La trascrizione della riunione ha raggiunto il limite del blocco senza terminare."
        )


class ASRRecoveryExhaustedError(RuntimeError):
    """Deterministic decoder exhaustion: retrying the same full chunk cannot help."""

    retryable = False


def _check_generation_end(tokens: int, last_token: int | None, eos_ids) -> bool:
    stops = [eos_ids] if isinstance(eos_ids, int) else (eos_ids or [])
    ended = last_token is not None and last_token in stops
    if tokens >= MAX_NEW_TOKENS and not ended:
        raise ASRTokenLimitError(tokens)
    return ended


def _choose_split_frame(waveform, sample_rate: int) -> int:
    """Choose a short low-energy interval close to the midpoint, without dropping frames."""
    frames = len(waveform)
    middle = frames // 2
    minimum = MIN_RECOVERY_WINDOW_S * sample_rate
    lower = max(minimum, middle - SPLIT_SEARCH_RADIUS_S * sample_rate)
    upper = min(frames - minimum, middle + SPLIT_SEARCH_RADIUS_S * sample_rate)
    if lower > upper:
        raise ValueError("Finestra troppo corta per suddivisione Qwen")
    stride = max(1, sample_rate // 10)
    half_window = max(1, sample_rate // 20)
    candidates = set(range(lower, upper + 1, stride))
    candidates.update((lower, middle, upper))
    def score(position: int):
        neighborhood = waveform[
            max(0, position - half_window) : min(frames, position + half_window)
        ].astype("float64")
        energy = float((neighborhood * neighborhood).mean())
        return energy, abs(position - middle)
    return min(candidates, key=score)


def verify_decode_coverage(pcm16: bytes, attempts: list[dict]) -> None:
    """Check every actual decoder window against the original PCM, not just requested chunks."""
    if not pcm16 or len(pcm16) % 2 or not isinstance(attempts, list) or not attempts:
        raise RuntimeError("Audit Qwen incompleto: nessuna finestra audio valida")
    frames = len(pcm16) // 2
    completed = []
    for entry in attempts:
        start, end = entry.get("start_frame"), entry.get("end_frame")
        if (not isinstance(start, int) or not isinstance(end, int)
                or not 0 <= start < end <= frames):
            raise RuntimeError("Audit Qwen: intervallo di decodifica non valido")
        if entry.get("status") not in {"completed", "token_limit"}:
            raise RuntimeError("Audit Qwen: esito di decodifica sconosciuto")
        actual = hashlib.sha256(pcm16[start * 2 : end * 2]).hexdigest()
        if actual != entry.get("pcm_sha256"):
            raise RuntimeError("Audit Qwen: il blocco decodificato non corrisponde all'audio")
        if entry["status"] == "completed":
            completed.append((start, end))
    covered = 0
    for start, end in sorted(completed):
        if start != covered:
            raise RuntimeError("Audit Qwen: audio perso o decodificato più volte")
        covered = end
    if covered != frames:
        raise RuntimeError("Audit Qwen: la decodifica non copre tutto il blocco")


@contextmanager
def _xpu_loading_context(torch, model_utils):
    """Skip optional allocator preallocation on Arc devices without a memory query.

    Transformers 5.17 queries XPU free memory during its loading optimization.
    Integrated Arc does not implement that query. Actual weight loading still
    goes directly to XPU, with normal allocation failures and our memory guard.
    This context is used only inside the isolated meeting worker process.
    """
    try:
        torch.xpu.mem_get_info()
    except RuntimeError as exc:
        if "doesn't support querying the available free memory" not in str(exc):
            raise
    else:
        yield
        return
    original = model_utils.caching_allocator_warmup
    model_utils.caching_allocator_warmup = lambda *_args, **_kwargs: None
    try:
        yield
    finally:
        model_utils.caching_allocator_warmup = original


class EnglishASRBackend:
    def __init__(self, model_dir: Path, cancel: Event):
        self.model_dir = model_dir
        self.cancel = cancel
        self.is_running = False
        self.model = self.processor = self.torch = None

    def _check_cancelled(self) -> None:
        if self.cancel.is_set():
            raise EnglishPipelineCancelled()

    def start(self) -> None:
        self._check_cancelled()
        import torch
        from transformers import AutoModelForMultimodalLM, AutoProcessor, modeling_utils

        if not torch.xpu.is_available():
            raise RuntimeError(
                "Il motore riunioni richiede una GPU Intel XPU disponibile."
            )
        self.torch = torch
        torch.set_num_threads(2)
        torch.manual_seed(0)
        self.processor = AutoProcessor.from_pretrained(
            self.model_dir, local_files_only=True
        )
        self._check_cancelled()
        # Load weights directly on XPU: creating a complete CPU copy first
        # doubles peak memory on Intel GPUs sharing the computer's RAM.
        with _xpu_loading_context(torch, modeling_utils):
            self.model = AutoModelForMultimodalLM.from_pretrained(
                self.model_dir,
                local_files_only=True,
                dtype=torch.float16,
                device_map={"": "xpu"},
                attn_implementation="sdpa",
            ).eval()
        self._check_cancelled()
        self.is_running = True
        logger.info(
            "Qwen ASR XPU dtype richiesto=%s, caricato=%s, dichiarato=%s",
            torch.float16,
            getattr(self.model, "dtype", None),
            getattr(self.model.config, "dtype", None),
        )

    def _decode_window(self, waveform, language: str) -> tuple[str, int, bool]:
        """One generation only; no hidden retry or text truncation."""
        from transformers import StoppingCriteria, StoppingCriteriaList

        self._check_cancelled()
        cancel = self.cancel

        class CancelGeneration(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return cancel.is_set()

        inputs = self.processor.apply_transcription_request(
            audio=waveform, language=language
        )
        inputs = inputs.to("xpu", self.torch.float16)
        with self.torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=MAX_NEW_TOKENS,
                do_sample=False,
                stopping_criteria=StoppingCriteriaList([CancelGeneration()]),
            )
        self._check_cancelled()
        generated = output[:, inputs["input_ids"].shape[1] :]
        count = int(generated.shape[1])
        ended = _check_generation_end(
            count,
            int(generated[0, -1]) if count else None,
            self.model.generation_config.eos_token_id,
        )
        text = self.processor.decode(
            generated.cpu(), return_format="transcription_only"
        )[0]
        if not isinstance(text, str):
            raise TypeError("Il modello riunioni ha restituito una risposta non valida.")
        return text, count, ended

    def transcribe_audio(
        self,
        audio_data: bytes,
        *,
        language=None,
        prompt=None,
        verbose=False,
        vad=False,
        **kwargs,
    ):
        self._check_cancelled()
        language = meeting_language(language or "en")
        if vad:
            raise ValueError("Il motore riunioni usa finestre continue senza VAD.")
        if not self.is_running:
            raise RuntimeError("Il modello riunioni non è stato avviato.")
        import soundfile as sf

        waveform, sample_rate = sf.read(
            io.BytesIO(audio_data), dtype="float32", always_2d=True
        )
        if (
            sample_rate != 16000
            or waveform.shape[1] != 1
            or not 0 < len(waveform) <= 30 * sample_rate
        ):
            raise ValueError(
                "Il motore riunioni richiede blocchi mono a 16 kHz di massimo 30 secondi."
            )
        with wave.open(io.BytesIO(audio_data), "rb") as stream:
            if stream.getnchannels() != 1 or stream.getsampwidth() != 2:
                raise ValueError("L'audio Qwen deve essere PCM16 mono")
            pcm16 = stream.readframes(stream.getnframes())
        if len(pcm16) != 2 * len(waveform):
            raise RuntimeError("Letture PCM incoerenti nel motore Qwen")

        samples = waveform[:, 0]
        attempts: list[dict] = []
        segments: list[dict] = []

        def record(start: int, end: int, status: str, tokens: int, ended: bool):
            attempts.append(
                {
                    "start_frame": start,
                    "end_frame": end,
                    "pcm_sha256": hashlib.sha256(
                        pcm16[start * 2 : end * 2]
                    ).hexdigest(),
                    "status": status,
                    "generated_tokens": tokens,
                    "native_end_token": ended,
                }
            )

        def decode(start: int, end: int, depth: int) -> None:
            self._check_cancelled()
            try:
                text, tokens, ended = self._decode_window(
                    samples[start:end], language
                )
            except ASRTokenLimitError as exc:
                record(start, end, "token_limit", exc.tokens, False)
                logger.warning(
                    "Qwen ASR: limite token (%s) senza EOS; finestra %.2f–%.2f s; profondità=%s",
                    exc.tokens, start / sample_rate, end / sample_rate, depth,
                )
                if (
                    depth >= MAX_RECOVERY_SPLITS
                    or end - start < 2 * MIN_RECOVERY_WINDOW_S * sample_rate
                ):
                    raise ASRRecoveryExhaustedError(
                        "La trascrizione Qwen non termina neppure dopo la suddivisione "
                        f"del blocco {start / sample_rate:.2f}–{end / sample_rate:.2f} s"
                    ) from exc
                cut = start + _choose_split_frame(
                    samples[start:end], sample_rate
                )
                logger.info(
                    "Qwen ASR: recupero suddividendo %.2f–%.2f s a %.2f s",
                    start / sample_rate, end / sample_rate, cut / sample_rate,
                )
                decode(start, cut, depth + 1)
                decode(cut, end, depth + 1)
                return
            record(start, end, "completed", tokens, ended)
            if text.strip():
                segments.append(
                    {
                        "start": start / sample_rate,
                        "end": end / sample_rate,
                        "text": text,
                    }
                )

        decode(0, len(samples), 0)
        verify_decode_coverage(pcm16, attempts)
        recovered = any(row["status"] == "token_limit" for row in attempts)
        text = (
            segments[0]["text"] if not recovered and segments
            else " ".join(segment["text"].strip() for segment in segments)
        )
        completed = [row for row in attempts if row["status"] == "completed"]
        if recovered:
            logger.info(
                "Qwen ASR: recupero completato; sottofinestre=%s; tentativi al limite=%s",
                len(completed), sum(row["status"] == "token_limit" for row in attempts),
            )
        duration = len(samples) / sample_rate
        response = {
            "text": text,
            "segments": segments,
            "duration": duration,
            "language": language,
            "generated_tokens": sum(row["generated_tokens"] for row in completed),
            "native_end_token": all(row["native_end_token"] for row in completed),
            "coarse_segment_timing": True,
            "recovered_from_token_limit": recovered,
            "decoder_attempts": attempts,
        }
        return response if verbose else text

    def abort_active_request(self) -> None:
        self.cancel.set()

    def stop(self) -> None:
        self.is_running = False
        self.model = self.processor = None
        gc.collect()
        if self.torch is not None:
            self.torch.xpu.empty_cache()
