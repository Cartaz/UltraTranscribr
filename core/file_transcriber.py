# core/file_transcriber.py
"""Thread per la trascrizione di file audio con whisper-server SYCL.

A differenza di TranscriberThread (che legge dal BufferManager in tempo
reale), questo thread trascrive un file audio completo inviandolo al
server whisper.cpp tramite l'API REST. Emette i segmenti tramite
l'EventBus.

Se l'endpoint e /inference (legacy) e il file non e WAV, il file
viene convertito automaticamente in WAV 16kHz mono tramite ffmpeg
prima dell'invio, perche l'endpoint /inference supporta solo WAV.
L'endpoint /v1/audio/transcriptions supporta nativamente MP3, FLAC
e altri formati.

Se isolate_vocals=True e song_mode=True, Demucs separa la voce dalla
musica prima della trascrizione, come nella versione originale.

Classes:
    FileTranscriberThread: Thread consumer per trascrizione file.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from config.constants import SYCLDefaults
from config.settings import Settings
from core.event_bus import EventBus
from core.models import StatusEnum
from core.whisper_backend import WhisperBackend, _alternate_endpoint

logger = logging.getLogger(__name__)

# ── Range di progresso per ogni fase ──────────────────────────
DEMUCS_END = 48
LOAD_START_NO_DEMUCS = 0
LOAD_END_NO_DEMUCS = 5
LOAD_START_DEMUCS = 48
LOAD_END_DEMUCS = 55
TRANSCRIBE_START_NO_DEMUCS = 5
TRANSCRIBE_START_DEMUCS = 55


class FileTranscriberThread(threading.Thread):
    """Thread che trascrive un file audio usando whisper-server SYCL.

    Il file audio viene inviato direttamente al server whisper.cpp
    tramite l'endpoint API rilevato automaticamente. Se l'endpoint
    e /inference (legacy) e il file non e WAV, viene convertito
    automaticamente tramite ffmpeg.

    Args:
        file_path: Percorso assoluto del file audio.
        backend: WhisperBackend per la comunicazione col server.
        settings: Impostazioni dell'applicazione.
        song_mode: True se il file e una canzone o contiene musica.
        isolate_vocals_flag: True per isolare la voce con Demucs.
    """

    def __init__(
        self,
        file_path: str,
        backend: WhisperBackend,
        settings: Settings,
        song_mode: bool = False,
        isolate_vocals_flag: bool = False,
    ) -> None:
        super().__init__(daemon=True, name="FileTranscriberThread")
        self._file_path = file_path
        self._backend = backend
        self._settings = settings
        self._song_mode = song_mode
        self._isolate_vocals = isolate_vocals_flag
        self._stop_event = threading.Event()
        self._vocal_path: Optional[str] = None
        self._has_demucs = self._isolate_vocals and self._song_mode
        self._converted_wav_path: Optional[str] = None

    def run(self) -> None:
        """Loop principale: isola voce, trascrive, emette segmenti."""
        bus = EventBus()
        transcribe_path = self._file_path

        # ── Fase 1: Isolamento vocale (opzionale) ──────────────────
        if self._isolate_vocals and self._song_mode:
            self._run_vocal_isolation(bus)

        # ── Fase 2: Trascrizione via server ────────────────────────
        load_start = LOAD_START_DEMUCS if self._has_demucs else LOAD_START_NO_DEMUCS
        bus.emit("file_transcriber_status_changed", StatusEnum.RUNNING.value)
        bus.emit("file_transcriber_progress", load_start)

        logger.info("FileTranscriberThread avviato -- file: %s", transcribe_path)

        try:
            self._transcribe_file(transcribe_path)
        except Exception as exc:
            if not self._stop_event.is_set():
                logger.error("Errore trascrizione file: %s", exc)
                bus.emit("file_transcriber_error", f"Errore trascrizione: {exc}")
                bus.emit("file_transcriber_status_changed", StatusEnum.ERROR.value)
        else:
            if not self._stop_event.is_set():
                bus.emit("file_transcriber_status_changed", StatusEnum.COMPLETED.value)
                bus.emit("file_transcriber_completed", None)
                logger.info("Trascrizione file completata")
        finally:
            bus.emit("file_transcriber_status_changed", StatusEnum.STOPPED.value)
            logger.info("FileTranscriberThread fermato")
            self._cleanup()

    def stop(self) -> None:
        """Segnala al thread di fermarsi."""
        self._stop_event.set()

    def _run_vocal_isolation(self, bus: EventBus) -> None:
        """Esegue l'isolamento vocale con Demucs se disponibile.

        Args:
            bus: Event bus per notificare il progresso.
        """
        from core.vocal_isolator import cleanup_vocals, isolate_vocals, is_demucs_available

        if not is_demucs_available():
            logger.warning(
                "Demucs non installato -- isolamento vocale non disponibile. "
                "Per attivarlo: pip install demucs")
            self._has_demucs = False
            return

        bus.emit("file_transcriber_status_changed", StatusEnum.ISOLATING_VOCALS.value)
        bus.emit("file_transcriber_progress", 0)
        logger.info("Avvio isolamento vocale con Demucs...")

        def _on_demucs_progress(percent: int) -> None:
            bus.emit("file_transcriber_progress", min(percent, DEMUCS_END))

        self._vocal_path = isolate_vocals(
            input_path=self._file_path,
            model_name="htdemucs",
            device="cpu",
            stop_event=self._stop_event,
            progress_callback=_on_demucs_progress,
        )

        if self._vocal_path:
            logger.info("Isolamento vocale completato -- trascrivo: %s", self._vocal_path)
            bus.emit("file_transcriber_progress", DEMUCS_END)
        else:
            if self._stop_event.is_set():
                return
            logger.warning("Isolamento vocale fallito, trascrivo il file originale")
            self._has_demucs = False

    def _transcribe_file(self, file_path: str) -> None:
        """Trascrive il file audio inviandolo al server whisper.

        Invia il file come multipart/form-data all'endpoint API
        rilevato automaticamente dal backend. Se l'endpoint e
        /inference e il file non e WAV, lo converte automaticamente
        tramite ffmpeg. Se la richiesta fallisce con 404, prova
        automaticamente l'endpoint alternativo.

        Su errore 400, tenta un retry con un formato di richiesta
        minimale (solo file + response_format, senza language) per
        gestire eventuali incompatibilita dell'endpoint /inference.

        Args:
            file_path: Percorso del file da trascribere.
        """
        bus = EventBus()
        endpoint = self._backend.api_endpoint
        is_inference = endpoint == "/inference"

        # Prepara il file da inviare (converte se necessario)
        send_path = self._prepare_file(file_path, force_wav=is_inference)

        if self._stop_event.is_set():
            return

        result = None

        # Prova l'endpoint corrente; se 404 o 500 con VAD, fallback.
        # range(3): spazio per VAD fallback + endpoint change + retry finale
        for attempt in range(3):
            endpoint = self._backend.api_endpoint
            url = f"{self._backend.server_url}{endpoint}"
            is_inference = endpoint == "/inference"
            boundary = "----UltraTranscribrFileBoundary"

            # Prima con language (se configurato)
            body = self._build_file_multipart(send_path, boundary,
                                              openai_compat=not is_inference,
                                              include_language=True)
            headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            }
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")

            try:
                file_size = os.path.getsize(send_path)
                # Log dettagliato: mostra byte per file piccoli (< 1 KB),
                # altrimenti KB. Questo aiuta a diagnosticare file vuoti
                # o corrotti che mostravano "0 KB" ambiguo.
                if file_size < 1024:
                    size_str = f"{file_size} B"
                else:
                    size_str = f"{file_size // 1024} KB"
                logger.info(
                    "Invio file a %s (%s, path=%s, language=%s)",
                    endpoint, size_str, send_path, self._settings.language,
                )
                if file_size == 0:
                    raise RuntimeError(
                        f"Il file e vuoto (0 byte): {send_path}. "
                        "Verificare che il file non sia corrotto."
                    )
                with urllib.request.urlopen(req, timeout=SYCLDefaults.REQUEST_TIMEOUT_S) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                # Leggi il body dell'errore per diagnostica
                error_body = ""
                try:
                    error_body = exc.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    pass

                if exc.code == 404 and attempt == 0:
                    # Endpoint non trovato -- prova l'alternativo
                    alt = _alternate_endpoint(endpoint)
                    logger.warning(
                        "Endpoint %s non trovato (404), provo %s",
                        endpoint, alt,
                    )
                    self._backend._api_endpoint = alt
                    # Se stiamo passando da /inference a /v1/...,
                    # non serve convertire perche' /v1/ supporta MP3
                    continue

                if exc.code == 400:
                    # Errore 400 -- la richiesta e malformata.
                    # Prova strategie di fallback in ordine.
                    fallback_result = self._handle_400_error(
                        send_path, endpoint, is_inference, boundary,
                        error_body, attempt,
                    )
                    if fallback_result is not None:
                        result = fallback_result
                        break

                    # Se il fallback non ha funzionato e siamo al primo
                    # tentativo, prova l'endpoint alternativo
                    if attempt == 0:
                        alt = _alternate_endpoint(endpoint)
                        logger.warning(
                            "Errore 400 su %s, provo endpoint alternativo %s",
                            endpoint, alt,
                        )
                        self._backend._api_endpoint = alt
                        continue

                if exc.code == 500:
                    # HTTP 500 -- il server ha crashato durante l'inferenza.
                    # Su iGPU Intel Arc con SYCL, il flag --vad puo causare
                    # errori 500 "failed to process audio". Tenta il fallback
                    # VAD: riavvia il server senza --vad e riprova.
                    if self._backend.trigger_vad_fallback():
                        logger.info(
                            "Fallback VAD applicato dopo errore 500, "
                            "riprovo trascrizione file..."
                        )
                        # Riprova con il server senza VAD
                        continue
                    # Se il fallback VAD non e applicabile (gia fatto o VAD
                    # non attivo), lascia che l'errore venga propagato

                raise RuntimeError(
                    f"Richiesta trascrizione file fallita: HTTP {exc.code} "
                    f"su {endpoint}. Risposta: {error_body}"
                ) from exc
            except urllib.error.URLError as exc:
                raise RuntimeError(
                    f"Richiesta trascrizione file fallita: {exc}"
                ) from exc

            # Successo -- esci dal loop
            break

        if result is None:
            raise RuntimeError("Trascrizione file fallita: nessun risultato ottenuto")

        text = result.get("text", "")
        if text.strip():
            from core.text_dedup import deduplicate_text
            cleaned = deduplicate_text(text.strip())
            bus.emit("file_transcriber_new_text", cleaned)
            bus.emit("file_transcriber_full_text", cleaned)

        bus.emit("file_transcriber_progress", 100)

    def _handle_400_error(
        self,
        send_path: str,
        endpoint: str,
        is_inference: bool,
        boundary: str,
        error_body: str,
        attempt: int,
    ) -> Optional[dict]:
        """Gestisce errori HTTP 400 con strategie di fallback.

        Prova nell'ordine:
        1. Richiesta senza campo language (alcune versioni di /inference
           non lo accettano)
        2. Conversione forzata in WAV con ffmpeg (se non ancora fatto)
        3. Richiesta con solo campo file (massima compatibilita)

        Args:
            send_path: Percorso del file da inviare.
            endpoint: Endpoint corrente.
            is_inference: Se True, l'endpoint e /inference.
            boundary: Separatore multipart.
            error_body: Corpo della risposta di errore.
            attempt: Numero del tentativo corrente.

        Returns:
            Dizionario del risultato JSON se il fallback ha successo,
            oppure None se tutti i fallback falliscono.
        """
        url = f"{self._backend.server_url}{endpoint}"

        # Traccia il path del file WAV eventualmente convertito in fallback 2,
        # inizializzato a None per evitare NameError in fallback 3 quando il
        # blocco fallback 2 viene saltato (file gia convertito da _prepare_file).
        converted: Optional[str] = None

        # Fallback 1: senza campo language
        logger.info(
            "Fallback 1: retry senza language (errore 400 su %s). Body: %s",
            endpoint, error_body[:200],
        )
        body = self._build_file_multipart(
            send_path, boundary,
            openai_compat=not is_inference,
            include_language=False,
        )
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=SYCLDefaults.REQUEST_TIMEOUT_S) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                logger.info("Fallback 1 (senza language) riuscito")
                return result
        except urllib.error.HTTPError:
            pass

        # Fallback 2: conversione forzata WAV (se non gia convertito)
        if not self._converted_wav_path:
            logger.info("Fallback 2: conversione forzata WAV...")
            converted = self._force_convert_wav(send_path)
            if converted and converted != send_path:
                body = self._build_file_multipart(
                    converted, boundary,
                    openai_compat=not is_inference,
                    include_language=False,
                )
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                try:
                    with urllib.request.urlopen(req, timeout=SYCLDefaults.REQUEST_TIMEOUT_S) as resp:
                        result = json.loads(resp.read().decode("utf-8"))
                        logger.info("Fallback 2 (WAV convertito) riuscito")
                        return result
                except urllib.error.HTTPError:
                    pass

        # Fallback 3: solo campo file (massima compatibilita)
        # Usa il file convertito (se disponibile) oppure il send_path originale.
        logger.info("Fallback 3: richiesta minimale (solo file)...")
        body = self._build_minimal_multipart(converted or send_path, boundary)
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=SYCLDefaults.REQUEST_TIMEOUT_S) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                logger.info("Fallback 3 (solo file) riuscito")
                return result
        except urllib.error.HTTPError as exc:
            error_detail = ""
            try:
                error_detail = exc.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            logger.error(
                "Tutti i fallback falliti. Ultimo errore: HTTP %d. Body: %s",
                exc.code, error_detail,
            )
            return None

    def _force_convert_wav(self, file_path: str) -> Optional[str]:
        """Converte forzatamente un file in WAV 16kHz mono tramite ffmpeg.

        Args:
            file_path: Percorso del file audio originale.

        Returns:
            Percorso del file WAV convertito, oppure None se fallito.
        """
        if not shutil.which("ffmpeg"):
            # Prova soundfile come fallback
            converted = self._convert_with_soundfile(file_path)
            if converted:
                return converted
            return None

        tmp_dir = tempfile.mkdtemp(prefix="ultratranscribr_")
        wav_path = os.path.join(tmp_dir, "audio_forced.wav")

        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", file_path,
                    "-ar", "16000",
                    "-ac", "1",
                    "-sample_fmt", "s16",
                    "-hide_banner", "-loglevel", "error",
                    wav_path,
                ],
                capture_output=True,
                timeout=120,
                check=True,
            )
            self._converted_wav_path = wav_path
            logger.info("Conversione forzata WAV completata: %s", wav_path)
            return wav_path
        except subprocess.CalledProcessError as exc:
            # Cattura e logga lo stderr di ffmpeg per diagnosticare il motivo
            # del fallimento (es. codec mancante, file corrotto, ecc.)
            stderr = ""
            if exc.stderr:
                stderr = exc.stderr.decode("utf-8", errors="replace")[:500]
            logger.warning(
                "Conversione ffmpeg fallita (exit %d). stderr: %s",
                exc.returncode, stderr,
            )
            # Prova soundfile come fallback
            converted = self._convert_with_soundfile(file_path)
            if converted:
                return converted
            return None
        except subprocess.TimeoutExpired as exc:
            logger.warning("Conversione ffmpeg timeout: %s", exc)
            converted = self._convert_with_soundfile(file_path)
            if converted:
                return converted
            return None

    def _convert_with_soundfile(self, file_path: str) -> Optional[str]:
        """Converte un file audio in WAV 16kHz mono usando soundfile.

        Fallback usato quando ffmpeg non e disponibile o fallisce.
        Richiede libsndfile >= 1.1.0 per il supporto MP3. Se la lettura
        fallisce (es. libsndfile vecchio o formato non supportato),
        restituisce None.

        Args:
            file_path: Percorso del file audio originale.

        Returns:
            Percorso del file WAV convertito, oppure None se fallito.
        """
        try:
            import soundfile as sf
            import numpy as np
        except ImportError:
            logger.debug("soundfile non disponibile per fallback conversione")
            return None

        try:
            logger.info("Tentativo conversione con soundfile: %s", file_path)
            # Leggi il file audio (soundfile usa libsndfile che supporta
            # WAV, FLAC, OGG, MP3 (>= 1.1.0) e altri formati)
            audio, sr = sf.read(file_path, dtype="float32")

            # Converti in mono se necessario (canale 0)
            if audio.ndim > 1:
                audio = audio[:, 0]

            # Resample a 16kHz tramite interpolazione lineare (come audio_resampler.py)
            if sr != 16000:
                duration = audio.shape[0] / sr
                target_length = int(duration * 16000)
                if target_length <= 0:
                    logger.warning("Audio troppo corto per soundfile conversion")
                    return None
                orig_indices = np.arange(audio.shape[0], dtype=np.float64)
                target_indices = np.linspace(0, audio.shape[0] - 1, target_length)
                audio = np.interp(target_indices, orig_indices, audio).astype(np.float32)
                sr = 16000

            # Scrivi come WAV 16-bit PCM
            tmp_dir = tempfile.mkdtemp(prefix="ultratranscribr_sf_")
            wav_path = os.path.join(tmp_dir, "audio_converted.wav")

            # Converti float32 a int16
            audio_int = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
            sf.write(wav_path, audio_int, sr, subtype="PCM_16")

            self._converted_wav_path = wav_path
            logger.info("Conversione soundfile completata: %s", wav_path)
            return wav_path
        except Exception as exc:
            logger.warning(
                "Conversione soundfile fallita: %s: %s. "
                "Possibili cause: libsndfile vecchio (MP3 richiede >= 1.1.0), "
                "file corrotto, o formato non supportato.",
                type(exc).__name__, exc,
            )
            return None

    def _prepare_file(self, file_path: str, force_wav: bool = False) -> str:
        """Prepara il file audio per l'invio, convertendo se necessario.

        Se force_wav e True e il file non e WAV, lo converte in
        WAV 16kHz mono 16-bit tramite ffmpeg (con fallback soundfile).
        Il file convertito viene salvato in una directory temporanea
        e rimosso nel cleanup.

        Args:
            file_path: Percorso del file audio originale.
            force_wav: Se True, converte sempre in WAV.

        Returns:
            Percorso del file da inviare (originale o convertito).
        """
        is_wav = file_path.lower().endswith(".wav")

        if is_wav and not force_wav:
            return file_path

        if not force_wav and self._backend.api_endpoint != "/inference":
            # L'endpoint OpenAI-compatible supporta MP3 e altri formati
            return file_path

        # Conversione necessaria: usa ffmpeg
        if not shutil.which("ffmpeg"):
            # ffmpeg non installato: prova soundfile come fallback
            logger.warning(
                "ffmpeg non trovato. Provo conversione con soundfile per %s. "
                "Per installare ffmpeg: sudo pacman -S ffmpeg",
                Path(file_path).suffix,
            )
            converted = self._convert_with_soundfile(file_path)
            if converted:
                return converted
            # soundfile non ha funzionato: ritorna il file originale
            # (l'endpoint /inference lo rifiutera con 400, ma il fallback
            # all'endpoint alternativo verra tentato)
            return file_path

        # Crea un file WAV temporaneo
        tmp_dir = tempfile.mkdtemp(prefix="ultratranscribr_")
        wav_path = os.path.join(tmp_dir, "audio_converted.wav")

        logger.info(
            "Conversione %s -> WAV 16kHz mono (ffmpeg)...",
            Path(file_path).suffix,
        )

        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", file_path,
                    "-ar", "16000",      # 16 kHz sample rate
                    "-ac", "1",          # mono
                    "-sample_fmt", "s16", # 16-bit PCM
                    "-hide_banner", "-loglevel", "error",
                    wav_path,
                ],
                capture_output=True,
                timeout=120,
                check=True,
            )
            self._converted_wav_path = wav_path
            logger.info("Conversione completata: %s", wav_path)
            return wav_path
        except subprocess.CalledProcessError as exc:
            # Cattura e logga lo stderr di ffmpeg per diagnosticare il motivo
            # del fallimento (es. codec mancante, file corrotto, ecc.).
            # Senza questo log, l'utente vede solo "exit status 183" senza
            # sapere il vero motivo.
            stderr = ""
            if exc.stderr:
                stderr = exc.stderr.decode("utf-8", errors="replace")[:500]
            logger.warning(
                "Conversione ffmpeg fallita (exit %d). stderr: %s",
                exc.returncode, stderr,
            )
            # Prova soundfile come fallback prima di arrendersi
            converted = self._convert_with_soundfile(file_path)
            if converted:
                return converted
            # Ritorna il file originale e speriamo che il server lo supporti
            return file_path
        except subprocess.TimeoutExpired as exc:
            logger.warning("Conversione ffmpeg timeout: %s", exc)
            converted = self._convert_with_soundfile(file_path)
            if converted:
                return converted
            return file_path

    def _build_file_multipart(self, file_path: str, boundary: str,
                               openai_compat: bool = True,
                               include_language: bool = True) -> bytes:
        """Costruisce il corpo multipart con il file audio.

        Per l'endpoint /inference (openai_compat=False), invia solo
        i campi file e language, senza campi OpenAI-specific (model,
        response_format) che l'endpoint originale non supporta e che
        potrebbero causare errori 500.

        Args:
            file_path: Percorso del file audio da inviare.
            boundary: Separatore multipart.
            openai_compat: Se True, include i campi OpenAI-specific
                (model, response_format). Mettere a False per /inference.
            include_language: Se True, include il campo "language".

        Returns:
            Corpo della richiesta come bytes.
        """
        path = Path(file_path)
        file_ext = path.suffix.lstrip(".") or "wav"
        content_type = f"audio/{file_ext}" if file_ext in ("wav", "mp3", "ogg", "flac") else "audio/wav"
        # MIME type corretto per MP3
        if file_ext == "mp3":
            content_type = "audio/mpeg"

        with open(file_path, "rb") as f:
            file_data = f.read()

        # Sanitize filename: rimuovi caratteri non-ASCII che potrebbero
        # causare problemi al parser multipart del server
        safe_name = path.name.encode("ascii", errors="replace").decode("ascii")

        parts: list[bytes] = []

        # Campo file
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="file"; '
            f'filename="{safe_name}"\r\n'.encode()
        )
        parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
        parts.append(file_data)
        parts.append(b"\r\n")

        # Campo lingua (opzionale)
        if include_language and self._settings.language:
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(b'Content-Disposition: form-data; name="language"\r\n\r\n')
            parts.append(f"{self._settings.language}\r\n".encode())

        # Parametri di decodifica per-request
        # Temperatura 0 per decodifica deterministica (no allucinazioni)
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(b'Content-Disposition: form-data; name="temperature"\r\n\r\n')
        parts.append(b"0\r\n")

        # Campi OpenAI-specific (solo per /v1/audio/transcriptions)
        if openai_compat:
            # Campo response_format - verbose_json per word timestamps
            # per massima accuratezza nella trascrizione dei file
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(b'Content-Disposition: form-data; name="response_format"\r\n\r\n')
            parts.append(b"verbose_json\r\n")

            # Campo modello
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(b'Content-Disposition: form-data; name="model"\r\n\r\n')
            parts.append(b"whisper-1\r\n")

        parts.append(f"--{boundary}--\r\n".encode())
        return b"".join(parts)

    def _build_minimal_multipart(self, file_path: str, boundary: str) -> bytes:
        """Costruisce un multipart minimale con solo il campo file.

        Usato come ultimo fallback quando le richieste complete
        falliscono con HTTP 400. Manda solo il file audio senza
        alcun campo aggiuntivo.

        Args:
            file_path: Percorso del file audio da inviare.
            boundary: Separatore multipart.

        Returns:
            Corpo della richiesta come bytes.
        """
        path = Path(file_path)
        file_ext = path.suffix.lstrip(".") or "wav"
        content_type = "audio/wav" if file_ext == "wav" else f"audio/{file_ext}"
        if file_ext == "mp3":
            content_type = "audio/mpeg"

        with open(file_path, "rb") as f:
            file_data = f.read()

        safe_name = path.name.encode("ascii", errors="replace").decode("ascii")

        parts: list[bytes] = []

        # Solo campo file
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="file"; '
            f'filename="{safe_name}"\r\n'.encode()
        )
        parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
        parts.append(file_data)
        parts.append(b"\r\n")

        parts.append(f"--{boundary}--\r\n".encode())
        return b"".join(parts)

    def _cleanup(self) -> None:
        """Rimuove i file temporanei (vocale e WAV convertito)."""
        if self._vocal_path:
            from core.vocal_isolator import cleanup_vocals
            cleanup_vocals(self._vocal_path)
            self._vocal_path = None

        if self._converted_wav_path:
            try:
                wav_dir = os.path.dirname(self._converted_wav_path)
                os.remove(self._converted_wav_path)
                # Rimuovi la directory temporanea se vuota
                if os.path.isdir(wav_dir) and not os.listdir(wav_dir):
                    os.rmdir(wav_dir)
            except OSError:
                pass
            self._converted_wav_path = None
