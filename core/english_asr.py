"""Qwen ASR for the optional English meeting worker process.

The production Whisper backend remains responsible for Live and Dictation.
This backend is owned by one isolated meeting job and uses Intel XPU only.
"""

from __future__ import annotations

import gc
import io
from pathlib import Path
from threading import Event

from core.english_models import EnglishPipelineCancelled
from core.meeting_engine import meeting_language


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
        from transformers import AutoModelForMultimodalLM, AutoProcessor

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
        self.model = (
            AutoModelForMultimodalLM.from_pretrained(
                self.model_dir,
                local_files_only=True,
                dtype=torch.float16,
                device_map=None,
                attn_implementation="sdpa",
            )
            .to("xpu")
            .eval()
        )
        self._check_cancelled()
        self.is_running = True

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
        from transformers import StoppingCriteria, StoppingCriteriaList

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
        cancel = self.cancel

        class CancelGeneration(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return cancel.is_set()

        inputs = self.processor.apply_transcription_request(
            audio=waveform[:, 0], language=language
        )
        inputs = inputs.to("xpu", self.torch.float16)
        with self.torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=512,
                do_sample=False,
                stopping_criteria=StoppingCriteriaList([CancelGeneration()]),
            )
        self._check_cancelled()
        generated = output[:, inputs["input_ids"].shape[1] :]
        stop = self.model.generation_config.eos_token_id
        stop = [stop] if isinstance(stop, int) else (stop or [])
        ended = generated.shape[1] > 0 and int(generated[0, -1]) in stop
        if generated.shape[1] >= 512 and not ended:
            raise RuntimeError(
                "La trascrizione della riunione ha raggiunto il limite del blocco senza terminare."
            )
        text = self.processor.decode(
            generated.cpu(), return_format="transcription_only"
        )[0]
        if not isinstance(text, str):
            raise TypeError("Il modello riunioni ha restituito una risposta non valida.")
        duration = len(waveform) / sample_rate
        response = {
            "text": text,
            "segments": [{"start": 0.0, "end": duration, "text": text}]
            if text.strip()
            else [],
            "duration": duration,
            "language": language,
            "generated_tokens": generated.shape[1],
            "native_end_token": ended,
            "coarse_segment_timing": True,
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
