"""Funzioni I/O e implementazioni strategie per l'isolamento vocale Demucs.

Helper caricamento/salvaggio audio, monkeypatch torchaudio e tqdm,
tre implementazioni strategiche (api, lowlevel, cli). Modulo interno.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def _load_audio_sf(path: str):
    """Carica audio con soundfile, restituisce (tensor, sample_rate)."""
    import numpy as np
    import soundfile as sf
    import torch
    wav_np, sr = sf.read(path)
    if wav_np.ndim == 1:
        wav_np = wav_np.reshape(1, -1)
    else:
        wav_np = wav_np.T
    return torch.from_numpy(wav_np).float(), sr


def _load_audio(path: str):
    """Carica un file audio, con fallback da torchaudio a soundfile."""
    try:
        import torchaudio
        return torchaudio.load(str(path))
    except (ImportError, RuntimeError) as exc:
        logger.info("torchaudio.load fallito (%s), uso soundfile", exc)
        return _load_audio_sf(path)


def _save_vocals_wav(output_path: str, vocals_tensor, sample_rate: int) -> None:
    """Salva il tensore vocale come WAV (soundfile con fallback a wave)."""
    import numpy as np
    vocals_np = vocals_tensor.cpu().numpy()
    if vocals_np.ndim == 2:
        vocals_np = vocals_np.T
    try:
        import soundfile as sf
        sf.write(output_path, vocals_np, sample_rate)
    except (ImportError, RuntimeError) as exc:
        logger.info("soundfile non disponibile (%s), uso wave stdlib", exc)
        import wave
        if vocals_np.ndim == 1:
            vocals_np = vocals_np.reshape(-1, 1)
        audio_int = np.clip(vocals_np * 32767, -32768, 32767).astype(np.int16)
        with wave.open(output_path, "w") as wf:
            wf.setnchannels(vocals_np.shape[1])
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int.tobytes())


def _patch_torchaudio() -> None:
    """Monkeypatcha torchaudio.load/save per usare soundfile (evita TorchCodec)."""
    try:
        import torchaudio
    except ImportError:
        logger.debug("torchaudio non installato, monkeypatch non necessaria")
        return
    if getattr(torchaudio, "_ultratranscribr_patched", False):
        return
    _orig_save = torchaudio.save

    def _sf_save(filepath, src, sample_rate, *args, **kwargs):
        try:
            import soundfile as sf
            audio_np = src.cpu().numpy()
            if audio_np.ndim == 2:
                audio_np = audio_np.T
            sf.write(str(filepath), audio_np, sample_rate)
        except (ImportError, RuntimeError) as exc:
            logger.debug("soundfile save fallito (%s), fallback torchaudio", exc)
            _orig_save(filepath, src, sample_rate, *args, **kwargs)

    _orig_load = torchaudio.load

    def _sf_load(filepath, *args, **kwargs):
        try:
            return _load_audio_sf(str(filepath))
        except (ImportError, RuntimeError) as exc:
            logger.debug("soundfile load fallito (%s), fallback torchaudio", exc)
            return _orig_load(filepath, *args, **kwargs)

    torchaudio.save = _sf_save
    torchaudio.load = _sf_load
    torchaudio._ultratranscribr_patched = True  # noqa: SLF001
    logger.info("torchaudio.load/save monkeypatchati per usare soundfile")


def _patch_tqdm_for_progress(
    progress_callback: Callable[[int], None],
    base_percent: int,
    range_percent: int,
) -> object:
    """Monkeypatcha tqdm per catturare il progresso di apply_model.

    Args:
        progress_callback: Funzione che riceve un intero 0-100.
        base_percent: Percentuale di inizio intervallo.
        range_percent: Ampiezza intervallo percentuale.

    Returns:
        Oggetto con metodo restore() per ripristinare tqdm originale.
    """
    import tqdm as _tqdm_mod
    _orig = _tqdm_mod.tqdm

    class _CaptureTqdm(_orig):
        """tqdm personalizzato che notifica il progresso via callback."""
        def update(self, n=1):
            result = super().update(n)
            try:
                if self.total and self.total > 0:
                    frac = min(self.n / self.total, 1.0)
                    pct = base_percent + int(frac * range_percent)
                    progress_callback(min(pct, base_percent + range_percent))
            except (ZeroDivisionError, AttributeError) as exc:
                logger.debug("Errore cattura progresso tqdm: %s", exc)
            return result

    _tqdm_mod.tqdm = _CaptureTqdm

    class _Restorer:
        """Ripristina tqdm originale."""
        def restore(self) -> None:
            _tqdm_mod.tqdm = _orig

    return _Restorer()


def _cleanup_tmp(tmp_dir: str, stop_event: Optional[object]) -> bool:
    """Se stop_event e attivo, rimuove tmp_dir e restituisce True."""
    if stop_event is not None and hasattr(stop_event, "is_set") and stop_event.is_set():
        logger.info("Isolamento vocale interrotto dall'utente")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return True
    return False


def _isolate_api(
    input_path: str, model_name: str, device: str,
    stop_event: Optional[object],
    progress_callback: Optional[Callable[[int], None]] = None,
) -> Optional[str]:
    """Isolamento vocale tramite demucs.api.Separator."""
    import demucs.api
    tmp_dir = tempfile.mkdtemp(prefix="ultratranscribr_vocals_")
    output_wav = Path(tmp_dir) / "vocals.wav"
    logger.info("Usando demucs.api.Separator")
    _patch_torchaudio()
    if progress_callback:
        progress_callback(2)
    logger.info("Caricamento modello Demucs '%s'...", model_name)
    separator = demucs.api.Separator(model=model_name, device=device, two_stems="vocals")
    logger.info("Modello Demucs caricato. Avvio separazione audio...")
    if progress_callback:
        progress_callback(5)
    restorer = _patch_tqdm_for_progress(progress_callback, 5, 43) if progress_callback else None
    try:
        _, separated = separator.separate_audio_file(str(input_path))
    finally:
        if restorer:
            restorer.restore()
    if _cleanup_tmp(tmp_dir, stop_event):
        return None
    vocals = separated.get("vocals")
    if vocals is None:
        logger.error("Traccia vocale non trovata nell'output Demucs (api)")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None
    if progress_callback:
        progress_callback(48)
    _save_vocals_wav(str(output_wav), vocals, separator.samplerate)
    if not output_wav.exists():
        logger.error("Salvataggio file vocale fallito (api)")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None
    logger.info("Traccia vocale isolata salvata: %s", output_wav)
    return str(output_wav)


def _isolate_lowlevel(
    input_path: str, model_name: str, device: str,
    stop_event: Optional[object],
    progress_callback: Optional[Callable[[int], None]] = None,
) -> Optional[str]:
    """Isolamento vocale tramite demucs.pretrained + demucs.apply."""
    import demucs.apply
    import demucs.pretrained
    import torch
    tmp_dir = tempfile.mkdtemp(prefix="ultratranscribr_vocals_")
    output_wav = Path(tmp_dir) / "vocals.wav"
    logger.info("Usando demucs.pretrained + demucs.apply (API basso livello)")
    logger.info("Caricamento modello Demucs '%s'...", model_name)
    model = demucs.pretrained.get_model(model_name)
    model.to(device)
    model.eval()
    logger.info("Modello caricato (%d sorgenti: %s)", len(model.sources), model.sources)
    if progress_callback:
        progress_callback(3)
    wav, sr = _load_audio(str(input_path))
    logger.info("File audio letto: shape=%s, sr=%d", list(wav.shape), sr)
    ref = wav.mean(0)
    wav_input = (wav - ref.mean()) / ref.std()
    restorer = _patch_tqdm_for_progress(progress_callback, 3, 45) if progress_callback else None
    logger.info(
        "Avvio separazione su %s — puo richiedere minuti su CPU, attendere...", device)
    try:
        with torch.no_grad():
            sources = demucs.apply.apply_model(
                model, wav_input[None], device=device, progress=bool(progress_callback))
    finally:
        if restorer:
            restorer.restore()
    logger.info("Separazione audio completata")
    if _cleanup_tmp(tmp_dir, stop_event):
        return None
    vocals_idx = next((i for i, s in enumerate(model.sources) if s == "vocals"), None)
    if vocals_idx is None:
        logger.error("Traccia vocale non trovata nelle sorgenti: %s", model.sources)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None
    vocals_tensor = sources[0, vocals_idx] * ref.std() + ref.mean()
    if progress_callback:
        progress_callback(48)
    _save_vocals_wav(str(output_wav), vocals_tensor, sr)
    if not output_wav.exists():
        logger.error("Salvataggio file vocale fallito (lowlevel)")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None
    logger.info("Traccia vocale isolata salvata: %s", output_wav)
    return str(output_wav)


def _isolate_cli(
    input_path: str, model_name: str, device: str,
    stop_event: Optional[object],
    progress_callback: Optional[Callable[[int], None]] = None,
) -> Optional[str]:
    """Isolamento vocale tramite CLI demucs.separate con monkeypatch."""
    import sys
    input_file = Path(input_path)
    tmp_dir = tempfile.mkdtemp(prefix="ultratranscribr_demucs_")
    logger.info("Usando demucs.separate CLI con monkeypatch torchaudio")
    _patch_torchaudio()
    if progress_callback:
        progress_callback(3)
    restorer = _patch_tqdm_for_progress(progress_callback, 3, 45) if progress_callback else None
    args = ["--two-stems=vocals", "-n", model_name, "-d", device, "-o", tmp_dir, str(input_path)]
    from demucs.separate import main as demucs_separate
    logger.info("Avvio separazione su %s — puo richiedere minuti su CPU, attendere...", device)
    old_argv = sys.argv
    try:
        sys.argv = ["demucs"] + args
        demucs_separate(args)
    finally:
        sys.argv = old_argv
        if restorer:
            restorer.restore()
    if _cleanup_tmp(tmp_dir, stop_event):
        return None
    demucs_output = Path(tmp_dir) / model_name / input_file.stem / "vocals.wav"
    if not demucs_output.exists():
        vocals_files = list(Path(tmp_dir).rglob("vocals.wav"))
        if not vocals_files:
            logger.error("File vocals.wav non trovato nell'output Demucs CLI")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None
        demucs_output = vocals_files[0]
    persist_dir = tempfile.mkdtemp(prefix="ultratranscribr_vocals_")
    output_wav = Path(persist_dir) / "vocals.wav"
    shutil.copy2(str(demucs_output), str(output_wav))
    shutil.rmtree(tmp_dir, ignore_errors=True)
    if progress_callback:
        progress_callback(48)
    logger.info("Traccia vocale isolata salvata: %s", output_wav)
    return str(output_wav)
