"""Demucs I/O helpers and separation strategies."""
from __future__ import annotations
import logging, shutil, tempfile
from pathlib import Path
from typing import Callable, Optional
logger = logging.getLogger(__name__)

def _load_audio_sf(path: str):
    import soundfile as sf, torch
    wav, sr = sf.read(path, always_2d=True, dtype="float32")
    return torch.from_numpy(wav.T.copy()), int(sr)

def _load_audio(path: str):
    try:
        import torchaudio
        return torchaudio.load(str(path))
    except Exception:
        return _load_audio_sf(path)

def _save_vocals_wav(output_path: str, vocals_tensor, sample_rate: int) -> None:
    import numpy as np, soundfile as sf
    wav = vocals_tensor.detach().cpu().numpy()
    if wav.ndim == 2:
        wav = wav.T
    sf.write(output_path, np.asarray(wav, dtype=np.float32), sample_rate)

def _cleanup_tmp(tmp_dir: str, stop_event: Optional[object]) -> bool:
    if stop_event is not None and hasattr(stop_event, "is_set") and stop_event.is_set():
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return True
    return False

def _isolate_api(input_path: str, model_name: str, device: str,
                 stop_event: Optional[object],
                 progress_callback: Optional[Callable[[int], None]] = None) -> Optional[str]:
    import demucs.api
    tmp = tempfile.mkdtemp(prefix="ultratranscribr_vocals_")
    out = Path(tmp) / "vocals.wav"
    if progress_callback: progress_callback(2)
    separator = demucs.api.Separator(model=model_name, device=device, two_stems="vocals")
    if progress_callback: progress_callback(5)
    _, separated = separator.separate_audio_file(str(input_path))
    if _cleanup_tmp(tmp, stop_event): return None
    vocals = separated.get("vocals")
    if vocals is None:
        shutil.rmtree(tmp, ignore_errors=True); return None
    _save_vocals_wav(str(out), vocals, separator.samplerate)
    if progress_callback: progress_callback(48)
    return str(out) if out.exists() else None

def _isolate_lowlevel(input_path: str, model_name: str, device: str,
                      stop_event: Optional[object],
                      progress_callback: Optional[Callable[[int], None]] = None) -> Optional[str]:
    import demucs.apply, demucs.pretrained, torch
    from demucs.audio import convert_audio
    tmp = tempfile.mkdtemp(prefix="ultratranscribr_vocals_")
    out = Path(tmp) / "vocals.wav"
    model = demucs.pretrained.get_model(model_name)
    model.to(device); model.eval()
    if progress_callback: progress_callback(3)
    wav, sr = _load_audio(input_path)
    wav = convert_audio(wav, int(sr), int(model.samplerate), int(model.audio_channels))
    ref = wav.mean(0)
    mean = ref.mean()
    std = ref.std().clamp_min(1e-8)
    normalized = (wav - mean) / std
    with torch.no_grad():
        sources = demucs.apply.apply_model(model, normalized[None], device=device,
                                           progress=bool(progress_callback))
    if _cleanup_tmp(tmp, stop_event): return None
    idx = next((i for i, name in enumerate(model.sources) if name == "vocals"), None)
    if idx is None:
        shutil.rmtree(tmp, ignore_errors=True); return None
    vocals = sources[0, idx] * std + mean
    _save_vocals_wav(str(out), vocals, int(model.samplerate))
    if progress_callback: progress_callback(48)
    return str(out) if out.exists() else None

def _isolate_cli(input_path: str, model_name: str, device: str,
                 stop_event: Optional[object],
                 progress_callback: Optional[Callable[[int], None]] = None) -> Optional[str]:
    from demucs.separate import main as demucs_main
    tmp = tempfile.mkdtemp(prefix="ultratranscribr_demucs_")
    try:
        if progress_callback: progress_callback(3)
        demucs_main(["--two-stems=vocals", "-n", model_name, "-d", device, "-o", tmp, input_path])
        if _cleanup_tmp(tmp, stop_event): return None
        found = list(Path(tmp).rglob("vocals.wav"))
        if not found: return None
        persist = tempfile.mkdtemp(prefix="ultratranscribr_vocals_")
        out = Path(persist) / "vocals.wav"
        shutil.copy2(found[0], out)
        if progress_callback: progress_callback(48)
        return str(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
