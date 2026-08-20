"""Resampling audio one-shot e streaming senza drift cumulativo."""
from __future__ import annotations

import logging

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)
WHISPER_SAMPLE_RATE = 16000


def resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resampling lineare one-shot, con lunghezza temporale corretta."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if audio.size == 0 or orig_sr == target_sr:
        return audio.copy() if audio.size else np.array([], dtype=np.float32)
    if orig_sr <= 0 or target_sr <= 0:
        raise ValueError("sample rate deve essere positivo")
    target_length = max(1, int(round(audio.size * target_sr / orig_sr)))
    src_positions = np.arange(audio.size, dtype=np.float64)
    dst_positions = np.arange(target_length, dtype=np.float64) * orig_sr / target_sr
    dst_positions = np.minimum(dst_positions, audio.size - 1)
    return np.interp(dst_positions, src_positions, audio).astype(np.float32)


class StreamingLinearResampler:
    """Resampler lineare stateful che conserva la fase tra i blocchi."""

    def __init__(self, orig_sr: int, target_sr: int) -> None:
        if orig_sr <= 0 or target_sr <= 0:
            raise ValueError("sample rate deve essere positivo")
        self.orig_sr = int(orig_sr)
        self.target_sr = int(target_sr)
        self._step = self.orig_sr / self.target_sr
        self._buffer = np.array([], dtype=np.float32)
        self._next_pos = 0.0

    def process(self, audio: np.ndarray, *, final: bool = False) -> np.ndarray:
        data = np.asarray(audio, dtype=np.float32).reshape(-1)
        if self.orig_sr == self.target_sr:
            return data.copy()
        if data.size:
            self._buffer = np.concatenate((self._buffer, data))
        if self._buffer.size == 0:
            return np.array([], dtype=np.float32)

        limit = self._buffer.size - (0 if final else 1)
        if limit <= 0 or self._next_pos > limit:
            return np.array([], dtype=np.float32)

        positions = np.arange(
            self._next_pos,
            limit + (1e-12 if final else 0),
            self._step,
        )
        if positions.size == 0:
            return np.array([], dtype=np.float32)
        positions = positions[positions <= self._buffer.size - 1]
        if positions.size == 0:
            return np.array([], dtype=np.float32)

        base = np.arange(self._buffer.size, dtype=np.float64)
        out = np.interp(positions, base, self._buffer).astype(np.float32)
        next_abs = float(positions[-1] + self._step)
        discard = min(int(next_abs), max(0, self._buffer.size - 1))
        if discard:
            self._buffer = self._buffer[discard:]
            next_abs -= discard
        self._next_pos = next_abs
        if final:
            self._buffer = np.array([], dtype=np.float32)
            self._next_pos = 0.0
        return out

    def flush(self) -> np.ndarray:
        return self.process(np.array([], dtype=np.float32), final=True)


def query_device_sample_rate(device: object) -> int:
    """Usa il sample rate nativo/default del device e resampla a 16 kHz.

    Alcuni device ALSA/PipeWire accettano ``check_input_settings`` a 16 kHz ma
    falliscono poi durante la preparazione dei buffer. Aprire il device al suo
    rate predefinito evita quella falsa compatibilita; il resampler streaming
    converte successivamente l'audio al rate richiesto da Whisper.
    """
    try:
        info = sd.query_devices(device)
        raw_rate = float(info.get("default_samplerate", 0) or 0)
        if not np.isfinite(raw_rate) or raw_rate <= 0:
            raise ValueError(f"default_samplerate non valido: {raw_rate}")
        native_sr = int(round(raw_rate))
        logger.info(
            "Dispositivo '%s': uso sample rate nativo/default %d Hz"
            " con resampling a %d Hz",
            info.get("name", "?"),
            native_sr,
            WHISPER_SAMPLE_RATE,
        )
        return native_sr
    except Exception as exc:
        logger.warning(
            "Impossibile determinare il sample rate nativo del dispositivo: %s; "
            "uso 48000 Hz",
            exc,
        )
        return 48000
