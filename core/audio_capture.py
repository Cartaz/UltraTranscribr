# core/audio_capture.py
"""Thread producer unificato per la cattura audio.

Gestisce due modalita di cattura in un unico thread:
  - Firefox/PipeWire: Usa il backend PulseAudio (device='pulse')
    con PULSE_SOURCE env var per selezionare il monitor source.
    Cattura con **callback** (non bloccante) a 16 kHz.
    Lo stream.stop() interrompe immediatamente la callback.
  - Microfono: Apre lo stream al sample rate nativo del dispositivo
    hardware (tipicamente 48000 Hz) e resampla a 16 kHz tramite
    interpolazione lineare (np.interp).
    Usa read() bloccante con stream.close() per rilascio immediato.

La logica di cattura monitor e microfono e delegata ai sottomoduli
audio_capture_monitor.py e audio_capture_mic.py per rispettare il
limite di 300 righe per file.

Classes:
    AudioCaptureThread: Thread producer per cattura audio.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np
import sounddevice as sd

from config.settings import AudioSource, Settings
from core.audio_capture_mic import microphone_capture_loop
from core.audio_capture_monitor import monitor_callback, monitor_capture_loop
from core.audio_resampler import WHISPER_SAMPLE_RATE, query_device_sample_rate
from core.buffer_manager import BufferManager
from core.pulse_helpers import (
    resolve_monitor_device,
    restore_pulse_source,
    set_pulse_source,
)

logger = logging.getLogger(__name__)


class AudioCaptureThread(threading.Thread):
    """Thread producer che cattura audio da monitor PipeWire o microfono.

    La strategia di cattura e selezionata automaticamente in base al tipo
    di dispositivo.

    Args:
        buffer: BufferManager in cui inserire i blocchi audio.
        settings: Impostazioni dell'applicazione.
        device_name: Nome del dispositivo (override di settings.sink_name).
        audio_source: Sorgente audio (firefox o microphone).

    Attributes:
        device_name: Nome del dispositivo audio attivo.
        error: Ultimo messaggio di errore, o None.
        is_running: Indica se il thread sta catturando attivamente.
    """

    def __init__(
        self,
        buffer: BufferManager,
        settings: Settings,
        device_name: Optional[str] = None,
        audio_source: Optional[str] = None,
    ) -> None:
        super().__init__(daemon=True, name="AudioCaptureThread")
        self._buffer = buffer
        self._settings = settings
        self._device_name = device_name
        self._audio_source = audio_source or settings.audio_source
        self._stop_event = threading.Event()
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()
        self._error: Optional[str] = None
        self._reconnect_delay = 2.0
        self._max_reconnect_attempts = 5
        self._native_sr: int = WHISPER_SAMPLE_RATE
        self._is_monitor: bool = False
        self._cb_accumulator: list = [np.array([], dtype=np.float32)]
        self._cb_lock = threading.Lock()
        # Traccia se set_pulse_source() e stato chiamato in questa sessione
        # per ripristinare PULSE_SOURCE solo quando e stato effettivamente
        # modificato. Evita di cancellare una variabile PULSE_SOURCE impostata
        # esternamente dall'utente quando si cattura da microfono.
        self._pulse_source_set: bool = False

    @property
    def device_name(self) -> Optional[str]:
        """Nome del dispositivo audio attivo."""
        return self._device_name or self._settings.sink_name

    @property
    def error(self) -> Optional[str]:
        """Ultimo messaggio di errore, o None."""
        with self._lock:
            return self._error

    @property
    def is_running(self) -> bool:
        """Indica se il thread sta catturando attivamente."""
        return self.is_alive() and not self._stop_event.is_set()

    # ═══════════════════════════════════════════════════════════════
    # Ciclo di vita del thread
    # ═══════════════════════════════════════════════════════════════

    def run(self) -> None:
        """Loop principale di cattura. Apre lo stream e cattura fino a stop()."""
        logger.info("AudioCaptureThread avviato — dispositivo: %s, fonte: %s",
                     self.device_name, self._audio_source)

        attempt = 0
        while not self._stop_event.is_set():
            try:
                self._open_stream()
                attempt = 0
                self._capture_loop()
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                with self._lock:
                    self._error = str(exc)
                logger.error("Errore stream audio: %s", exc)
                attempt += 1
                if attempt >= self._max_reconnect_attempts:
                    logger.error("Tentativi di riconnessione esauriti.")
                    break
                self._stop_event.wait(self._reconnect_delay)

        self._close_stream()
        # Ripristina PULSE_SOURCE solo se e stato modificato da set_pulse_source
        # in questa sessione (modalita monitor). In modalita microfono la
        # variabile non viene toccata e non deve essere ripristinata, per non
        # cancellare un eventuale PULSE_SOURCE impostato esternamente.
        if self._pulse_source_set:
            restore_pulse_source()
            self._pulse_source_set = False
        logger.info("AudioCaptureThread fermato")

    def stop(self) -> None:
        """Segnala al thread di fermarsi e rilascia il dispositivo.

        Comportamento differenziato per tipo di stream:

        - **Monitor (callback)**: ``stream.stop()`` interrompe la callback
          immediatamente.

        - **Microfono (ALSA)**: ``stream.stop()`` + ``stream.close()`` per
          forzare il rilascio del dispositivo e interrompere la ``read()``
          bloccante.
        """
        self._stop_event.set()
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception as exc:
                logger.debug("Errore fermando lo stream: %s", exc)

            if not self._is_monitor:
                try:
                    self._stream.close()
                except Exception as exc:
                    logger.debug("Errore chiudendo lo stream in stop: %s", exc)
                self._stream = None

    # ═══════════════════════════════════════════════════════════════
    # Gestione stream
    # ═══════════════════════════════════════════════════════════════

    def _determine_is_monitor(self) -> bool:
        """Determina se il dispositivo e un monitor source.

        Returns:
            True se il dispositivo e un monitor PipeWire/PulseAudio.
        """
        name = self.device_name or ""
        if self._audio_source == AudioSource.FIREFOX.value:
            return True
        return ".monitor" in name

    def _open_stream(self) -> None:
        """Apre un InputStream con la strategia appropriata."""
        self._is_monitor = self._determine_is_monitor()
        if self._is_monitor:
            self._open_stream_monitor()
        else:
            self._open_stream_microphone()

    def _open_stream_monitor(self) -> None:
        """Apre lo stream monitor con callback (non bloccante)."""
        device, pulse_source = resolve_monitor_device(self.device_name or "")
        if pulse_source:
            set_pulse_source(pulse_source)
            self._pulse_source_set = True
        else:
            self._pulse_source_set = False

        sr = WHISPER_SAMPLE_RATE
        logger.info("Apertura stream monitor (callback): device=%s, sr=%d", device, sr)

        self._cb_accumulator = [np.array([], dtype=np.float32)]
        self._stream = sd.InputStream(
            device=device, samplerate=sr,
            channels=self._settings.channels, dtype=self._settings.dtype,
            blocksize=0, latency="low",
            callback=self._monitor_cb_wrapper,
        )
        self._stream.start()

        with self._lock:
            self._error = None
        self._native_sr = sr
        logger.info("Stream audio monitor aperto con successo (callback)")

    def _monitor_cb_wrapper(self, indata, frames, time_info, status) -> None:
        """Wrapper che invoca monitor_callback con i parametri corretti."""
        monitor_callback(
            indata, frames, time_info, status,
            stop_event=self._stop_event,
            cb_lock=self._cb_lock,
            cb_accumulator=self._cb_accumulator,
            buffer=self._buffer,
            chunk_samples=self._settings.chunk_samples,
        )

    def _open_stream_microphone(self) -> None:
        """Apre lo stream per un dispositivo microfono (read bloccante)."""
        device = self.device_name
        self._native_sr = query_device_sample_rate(device)
        sr = self._native_sr

        logger.info("Apertura stream microfono: device=%s, sr=%d", device, sr)
        self._stream = sd.InputStream(
            device=device, samplerate=sr,
            channels=self._settings.channels, dtype=self._settings.dtype,
            blocksize=0, latency="low",
        )
        self._stream.start()

        with self._lock:
            self._error = None
        logger.info("Stream audio microfono aperto (native_sr=%d)", self._native_sr)

    def _close_stream(self) -> None:
        """Chiude lo stream audio in sicurezza."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                logger.warning("Errore chiusura stream: %s", exc)
            finally:
                self._stream = None

    # ═══════════════════════════════════════════════════════════════
    # Loop di cattura
    # ═══════════════════════════════════════════════════════════════

    def _capture_loop(self) -> None:
        """Loop di cattura — delega alla strategia appropriata."""
        if self._is_monitor:
            monitor_capture_loop(
                stop_event=self._stop_event,
                lock=self._lock,
                cb_lock=self._cb_lock,
                cb_accumulator=self._cb_accumulator,
                buffer=self._buffer,
            )
        else:
            microphone_capture_loop(
                stream=self._stream,
                stop_event=self._stop_event,
                lock=self._lock,
                buffer=self._buffer,
                chunk_samples=self._settings.chunk_samples,
                native_sr=self._native_sr,
                needs_resample=self._native_sr != WHISPER_SAMPLE_RATE,
            )
