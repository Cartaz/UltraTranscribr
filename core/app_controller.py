# core/app_controller.py
"""Controller principale dell'applicazione UltraTranscribr con SYCL.

Funge da interfaccia unica tra il livello UI e il livello Core.
Il controller gestisce il ciclo di vita del backend whisper-server
(avvio, health check, arresto), dei thread di cattura e trascrizione,
e comunica i cambiamenti di stato tramite l'event bus.

A differenza della versione faster-whisper, il modello non viene
caricato nei thread di trascrizione ma nel backend whisper-server,
che viene avviato una volta sola e condiviso tra trascrizione
live e da file.

Classes:
    AppController: Controller principale dell'applicazione.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from config.settings import AudioSource, Settings
from core.audio_capture import AudioCaptureThread
from core.buffer_manager import BufferManager
from core.event_bus import EventBus
from core.exceptions import GPUNotAvailableError, SinkNotFoundError
from core.file_transcriber import FileTranscriberThread
from core.models import StatusEnum
from core.sink_finder import find_source
from core.transcriber import TranscriberThread
from core.whisper_backend import WhisperBackend
from core.whisper_gpu_detect import detect_gpu_backend
from core.whisper_models import WhisperModelManager

logger = logging.getLogger(__name__)


class AppController:
    """Controller principale dell'applicazione UltraTranscribr.

    Gestisce il ciclo di vita del backend whisper-server e dei
    processi audio e di trascrizione (sia live che da file), e
    fornisce l'interfaccia pubblica che il livello UI utilizza.

    Attributes:
        settings: Impostazioni correnti dell'applicazione.
    """

    def __init__(self, settings: Settings) -> None:
        """Inizializza il controller con le impostazioni date.

        Verifica la disponibilita del backend SYCL e prepara il
        gestore del modello e del server.

        Args:
            settings: Impostazioni iniziali dell'applicazione.

        Raises:
            GPUNotAvailableError: Se SYCL non e disponibile.
        """
        self._settings = settings
        self._project_root = Path(__file__).resolve().parent.parent
        self._buffer = BufferManager(
            warn_threshold=settings.buffer_warn_threshold,
        )
        self._bus = EventBus()

        # Verifica backend GPU SYCL
        backend = detect_gpu_backend(self._project_root)
        if backend != "sycl":
            raise GPUNotAvailableError(
                "Backend SYCL non disponibile su questo sistema",
                detail="Verificare che Intel oneAPI, driver Level Zero e "
                       "Intel Compute Runtime siano installati.",
            )

        self._model_manager = WhisperModelManager()
        self._backend = WhisperBackend(settings, self._project_root)
        self._capture_thread: Optional[AudioCaptureThread] = None
        self._transcriber_thread: Optional[TranscriberThread] = None
        self._file_thread: Optional[FileTranscriberThread] = None
        self._backend_started = False

    @property
    def settings(self) -> Settings:
        """Impostazioni correnti dell'applicazione."""
        return self._settings

    @property
    def buffer(self) -> BufferManager:
        """Riferimento al BufferManager attivo."""
        return self._buffer

    @property
    def backend(self) -> WhisperBackend:
        """Riferimento al backend whisper-server."""
        return self._backend

    def ensure_backend_started(self) -> None:
        """Avvia il backend whisper-server se non ancora attivo.

        Scarica il modello da HuggingFace se non in cache, poi
        avvia whisper-server con SYCL e attende il health check.

        Raises:
            RuntimeError: Se il server non si avvia correttamente.
        """
        if self._backend_started and self._backend.is_running:
            return

        logger.info("Avvio backend whisper-server SYCL...")
        self._bus.emit("backend_status_changed", StatusEnum.LOADING_MODEL.value)

        model_path = self._model_manager.get_model_path(self._settings.model_size)
        self._backend.start(model_path)

        self._backend_started = True
        logger.info("Backend whisper-server pronto")

    def stop_backend(self) -> None:
        """Arresta il backend whisper-server."""
        if self._backend_started:
            self._backend.stop()
            self._backend_started = False
            logger.info("Backend whisper-server fermato")

    # ── Trascrizione Live ─────────────────────────────────────────

    def start_transcription(
        self,
        sink_name: Optional[str] = None,
        audio_source: Optional[str] = None,
        language: Optional[str] = None,
    ) -> None:
        """Avvia la cattura audio e la trascrizione live.

        Args:
            sink_name: Nome del sink audio. None per auto-detect.
            audio_source: Sorgente audio ("firefox" o "microphone").
            language: Lingua di trascrizione (ISO 639-1).

        Raises:
            SinkNotFoundError: Se il sink non viene trovato.
            RuntimeError: Se il backend non si avvia.
        """
        if self._capture_thread is not None or self._transcriber_thread is not None:
            logger.warning("Sessione live precedente attiva, la fermo")
            self.stop_transcription()

        self.ensure_backend_started()

        resolved_source = audio_source or self._settings.audio_source
        resolved_sink = self._resolve_sink(sink_name, resolved_source)
        self._buffer.clear()

        self._capture_thread = AudioCaptureThread(
            buffer=self._buffer, settings=self._settings,
            device_name=resolved_sink, audio_source=resolved_source,
        )
        self._transcriber_thread = TranscriberThread(
            buffer=self._buffer, backend=self._backend, settings=self._settings,
        )
        self._capture_thread.start()
        self._transcriber_thread.start()

        self._bus.emit("process_started",
                        {"sink": resolved_sink, "source": resolved_source})
        logger.info("Trascrizione live avviata — sink: %s", resolved_sink)

    def stop_transcription(self) -> None:
        """Ferma la cattura audio e la trascrizione live."""
        capture = self._capture_thread
        transcriber = self._transcriber_thread

        if capture:
            capture.stop()
        if transcriber:
            transcriber.stop()
        if capture:
            capture.join(timeout=8.0)
            if capture.is_alive():
                logger.warning("AudioCaptureThread non terminato")
        if transcriber:
            transcriber.join(timeout=8.0)

        self._capture_thread = None
        self._transcriber_thread = None
        self._bus.emit("process_stopped", None)
        logger.info("Trascrizione live fermata")

    def is_running(self) -> bool:
        """Verifica se la trascrizione live e attiva.

        Returns:
            True se il thread di cattura e vivo.
        """
        return (self._capture_thread is not None
                and self._capture_thread.is_alive())

    def is_draining(self) -> bool:
        """Verifica se il transcriber sta svuotando il buffer.

        Returns:
            True se la cattura e fermata ma il transcriber e ancora attivo.
        """
        return (self._capture_thread is None
                and self._transcriber_thread is not None
                and self._transcriber_thread.is_alive())

    def stop_listening(self) -> None:
        """Ferma la cattura audio ma lascia il transcriber svuotare il buffer."""
        capture = self._capture_thread
        if capture is None:
            logger.warning("Nessuna cattura attiva da fermare")
            return

        capture.stop()
        capture.join(timeout=8.0)
        if capture.is_alive():
            logger.warning("AudioCaptureThread non terminato in stop_listening")

        self._capture_thread = None
        self._buffer.close_input()

        self._bus.emit("capture_stopped", None)
        logger.info("Cattura fermata — transcriber in drain mode")

    # ── Trascrizione File ─────────────────────────────────────────

    def start_file_transcription(
        self,
        file_path: str,
        language: Optional[str] = None,
        model_size: Optional[str] = None,
        song_mode: bool = False,
        isolate_vocals_flag: bool = False,
    ) -> None:
        """Avvia la trascrizione di un file audio.

        Args:
            file_path: Percorso del file audio (.mp3 o .wav).
            language: Lingua di trascrizione (ISO 639-1).
            model_size: Dimensione del modello Whisper.
            song_mode: True se il file e una canzone o contiene musica.
            isolate_vocals_flag: True per isolare la voce con Demucs.
        """
        if self._file_thread is not None:
            logger.warning("Trascrizione file precedente attiva, la fermo")
            self.stop_file_transcription()

        self.ensure_backend_started()

        self._file_thread = FileTranscriberThread(
            file_path=file_path, backend=self._backend,
            settings=self._settings, song_mode=song_mode,
            isolate_vocals_flag=isolate_vocals_flag,
        )
        self._file_thread.start()
        logger.info("Trascrizione file avviata — %s", file_path)

    def stop_file_transcription(self) -> None:
        """Ferma la trascrizione del file audio."""
        if self._file_thread:
            self._file_thread.stop()
            self._file_thread.join(timeout=8.0)
            self._file_thread = None
        logger.info("Trascrizione file fermata")

    def is_file_transcribing(self) -> bool:
        """Verifica se la trascrizione file e attiva.

        Returns:
            True se il thread di trascrizione file e vivo.
        """
        return (self._file_thread is not None
                and self._file_thread.is_alive())

    # ── Impostazioni ──────────────────────────────────────────────

    def update_settings(self, **overrides: object) -> None:
        """Aggiorna le impostazioni con i valori forniti.

        Args:
            **overrides: Campi da aggiornare e loro nuovi valori.
        """
        self._settings = self._settings.with_(**overrides)
        self._settings.save()
        self._bus.emit("config_changed", overrides)
        logger.info("Impostazioni aggiornate: %s", overrides)

    def subscribe(self, event: str, handler: Callable) -> None:
        """Iscrive un handler a un evento dell'event bus.

        Args:
            event: Nome dell'evento.
            handler: Funzione callback.
        """
        self._bus.subscribe(event, handler)

    # ── Interno ───────────────────────────────────────────────────

    def _resolve_sink(
        self,
        sink_name: Optional[str],
        audio_source: str,
    ) -> str:
        """Risolve il nome del sink, con auto-detect se necessario.

        Args:
            sink_name: Nome specifico, o None per auto-detect.
            audio_source: Sorgente audio ("firefox" o "microphone").

        Returns:
            Nome del sink risolto.

        Raises:
            SinkNotFoundError: Se l'auto-detect fallisce.
        """
        if sink_name is not None:
            return sink_name

        detected = find_source(self._settings, audio_source=audio_source)
        if detected is None:
            if audio_source == AudioSource.FIREFOX.value:
                raise SinkNotFoundError(
                    "Impossibile trovare automaticamente il sink di Firefox",
                    detail="Assicurati che Firefox sia aperto e riproduca audio",
                )
            raise SinkNotFoundError(
                "Impossibile trovare automaticamente il microfono",
                detail="Assicurati che il microfono sia collegato e funzionante",
            )
        return detected
