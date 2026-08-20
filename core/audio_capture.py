"""Thread producer unificato per Firefox/PipeWire e microfono."""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import numpy as np
import sounddevice as sd

from config.constants import ProcessDefaults
from config.settings import AudioSource, Settings
from core.audio_capture_mic import microphone_capture_loop
from core.audio_capture_monitor import monitor_callback, monitor_capture_loop
from core.audio_resampler import WHISPER_SAMPLE_RATE, query_device_sample_rate
from core.buffer_manager import BufferManager
from core.event_bus import EventBus
from core.pulse_helpers import (
    resolve_monitor_device,
    restore_pulse_source,
    set_pulse_source,
)

logger = logging.getLogger(__name__)


class AudioCaptureThread(threading.Thread):
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
        self._reconnect_delay = ProcessDefaults.RECONNECT_DELAY
        self._max_reconnect_attempts = ProcessDefaults.MAX_RECONNECT_ATTEMPTS
        self._native_sr = WHISPER_SAMPLE_RATE
        self._is_monitor = False
        self._cb_accumulator = [np.array([], dtype=np.float32)]
        self._cb_lock = threading.Lock()
        self._pulse_source_set = False

    @property
    def device_name(self) -> Optional[str]:
        return self._device_name or self._settings.sink_name

    @property
    def error(self) -> Optional[str]:
        with self._lock:
            return self._error

    @property
    def is_running(self) -> bool:
        return self.is_alive() and not self._stop_event.is_set()

    def run(self) -> None:
        logger.info(
            "AudioCaptureThread avviato — device=%s source=%s",
            self.device_name,
            self._audio_source,
        )
        attempt = 0
        fatal_error: Optional[str] = None
        try:
            while not self._stop_event.is_set():
                opened_at: Optional[float] = None
                try:
                    self._open_stream()
                    opened_at = time.monotonic()
                    self._capture_loop()
                    if self._stop_event.is_set():
                        break
                except Exception as exc:
                    if self._stop_event.is_set():
                        break
                    self._close_stream()
                    with self._lock:
                        self._error = str(exc)

                    # Un errore dopo una sessione stabile non appartiene alla
                    # precedente raffica di reconnect; riparte da tentativo 1.
                    if (
                        opened_at is not None
                        and time.monotonic() - opened_at >= 10.0
                    ):
                        attempt = 0
                    attempt += 1

                    logger.error(
                        "Errore stream audio (%d/%d): %s",
                        attempt,
                        self._max_reconnect_attempts,
                        exc,
                    )
                    if attempt >= self._max_reconnect_attempts:
                        fatal_error = str(exc)
                        break
                    self._stop_event.wait(self._reconnect_delay)
        finally:
            self._close_stream()
            if self._pulse_source_set:
                restore_pulse_source()
                self._pulse_source_set = False
            if fatal_error and not self._stop_event.is_set():
                self._buffer.close_input()
                EventBus().emit(
                    "transcriber_error",
                    "Cattura audio terminata dopo "
                    f"{self._max_reconnect_attempts} tentativi: {fatal_error}",
                )
            logger.info("AudioCaptureThread fermato")

    def stop(self) -> None:
        """Richiede l'arresto senza chiamare PortAudio dal thread chiamante.

        ``stream.read()``/callback e ``stop()/close()`` concorrenti possono
        produrre errori ALSA/PortAudio. Il worker osserva l'evento e chiude lo
        stream nel proprio ``finally``.
        """
        self._stop_event.set()

    def _determine_is_monitor(self) -> bool:
        name = self.device_name or ""
        return (
            self._audio_source == AudioSource.FIREFOX.value
            or ".monitor" in name
        )

    def _open_stream(self) -> None:
        self._is_monitor = self._determine_is_monitor()
        if self._is_monitor:
            self._open_stream_monitor()
        else:
            self._open_stream_microphone()

    def _open_stream_monitor(self) -> None:
        device, pulse_source = resolve_monitor_device(self.device_name or "")
        if pulse_source:
            set_pulse_source(pulse_source)
            self._pulse_source_set = True
        self._cb_accumulator = [np.array([], dtype=np.float32)]
        self._stream = sd.InputStream(
            device=device,
            samplerate=WHISPER_SAMPLE_RATE,
            channels=self._settings.channels,
            dtype=self._settings.dtype,
            blocksize=0,
            latency="low",
            callback=self._monitor_cb_wrapper,
        )
        self._stream.start()
        self._native_sr = WHISPER_SAMPLE_RATE
        with self._lock:
            self._error = None

    def _monitor_cb_wrapper(self, indata, frames, time_info, status) -> None:
        monitor_callback(
            indata,
            frames,
            time_info,
            status,
            stop_event=self._stop_event,
            cb_lock=self._cb_lock,
            cb_accumulator=self._cb_accumulator,
            buffer=self._buffer,
            chunk_samples=self._settings.chunk_samples,
        )

    def _open_stream_microphone(self) -> None:
        self._native_sr = query_device_sample_rate(self.device_name)
        self._stream = sd.InputStream(
            device=self.device_name,
            samplerate=self._native_sr,
            channels=self._settings.channels,
            dtype=self._settings.dtype,
            blocksize=0,
            latency="low",
        )
        self._stream.start()
        with self._lock:
            self._error = None

    def _close_stream(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception as exc:
            logger.debug("Errore chiusura stream: %s", exc)

    def _capture_loop(self) -> None:
        if self._is_monitor:
            monitor_capture_loop(
                stop_event=self._stop_event,
                lock=self._lock,
                cb_lock=self._cb_lock,
                cb_accumulator=self._cb_accumulator,
                buffer=self._buffer,
            )
        else:
            assert self._stream is not None
            microphone_capture_loop(
                stream=self._stream,
                stop_event=self._stop_event,
                lock=self._lock,
                buffer=self._buffer,
                chunk_samples=self._settings.chunk_samples,
                native_sr=self._native_sr,
                needs_resample=self._native_sr != WHISPER_SAMPLE_RATE,
            )
