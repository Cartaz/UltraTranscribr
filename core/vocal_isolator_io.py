"""Demucs-infer I/O and XPU inference helpers."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional


def _load_audio_soundfile(path: str) -> tuple[Any, int]:
    import soundfile as sf
    import torch

    wav, sample_rate = sf.read(path, always_2d=True, dtype="float32")
    if wav.size == 0:
        raise RuntimeError("file audio vuoto")
    return torch.from_numpy(wav.T.copy()), int(sample_rate)


def _save_vocals_wav(output_path: str, vocals_tensor: Any, sample_rate: int) -> None:
    import numpy as np
    import soundfile as sf

    wav = vocals_tensor.detach().cpu().numpy()
    if wav.ndim == 2:
        wav = wav.T
    sf.write(output_path, np.asarray(wav, dtype=np.float32), sample_rate)


def _cancelled(stop_event: Optional[object]) -> bool:
    return bool(
        stop_event is not None
        and hasattr(stop_event, "is_set")
        and stop_event.is_set()
    )


def isolate_vocals_xpu(
    input_path: str,
    model_name: str,
    device: Any,
    stop_event: Optional[object],
    progress_callback: Optional[Callable[[int], None]] = None,
) -> str:
    """Run the single supported Demucs path using a validated XPU device."""
    import torch
    from demucs_infer import apply as demucs_apply
    from demucs_infer import pretrained as demucs_pretrained
    from demucs_infer.audio import convert_audio

    tmp = tempfile.mkdtemp(prefix="ultratranscribr_vocals_")
    out = Path(tmp) / "vocals.wav"
    try:
        if progress_callback:
            progress_callback(2)
        model = demucs_pretrained.get_model(model_name)
        model.to(device)
        model.eval()

        wav, sample_rate = _load_audio_soundfile(input_path)
        wav = convert_audio(
            wav,
            int(sample_rate),
            int(model.samplerate),
            int(model.audio_channels),
        )
        if _cancelled(stop_event):
            raise RuntimeError("isolamento vocale interrotto")

        ref = wav.mean(0)
        mean = ref.mean()
        std = ref.std().clamp_min(1e-8)
        normalized = (wav - mean) / std
        if progress_callback:
            progress_callback(5)

        try:
            with torch.inference_mode():
                sources = demucs_apply.apply_model(
                    model,
                    normalized[None],
                    device=device,
                    progress=False,
                )
        except Exception as exc:
            raise RuntimeError(f"inferenza Demucs XPU fallita: {exc}") from exc

        if _cancelled(stop_event):
            raise RuntimeError("isolamento vocale interrotto")
        try:
            source_index = next(i for i, name in enumerate(model.sources) if name == "vocals")
        except StopIteration as exc:
            raise RuntimeError("il modello Demucs non espone lo stem vocals") from exc

        vocals = sources[0, source_index] * std + mean
        _save_vocals_wav(str(out), vocals, int(model.samplerate))
        if not out.is_file():
            raise RuntimeError("Demucs non ha prodotto il file vocals.wav")
        if progress_callback:
            progress_callback(48)
        return str(out)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
