# core/whisper_backend.py
"""Gestione del server whisper.cpp come processo figlio con accelerazione SYCL.

Avvia whisper-server compilato con SYCL come processo figlio
(subprocess.Popen), configurando le variabili d'ambiente necessarie
per il backend Level Zero. La comunicazione avviene tramite API REST.

Lo stdout e stderr del server vengono rediretti su un file di log
per evitare che il buffer PIPE (64 KB) si riempia e blocchi il
processo. Il health check avviene tramite richieste HTTP periodiche
all'endpoint /health.

Il server viene avviato senza flag GPU aggiuntivi: quando il binary
e compilato con SYCL (-DGGML_SYCL=1), la GPU viene usata
automaticamente. Non implementa fallback CPU, conforme al requisito
di solo GPU.

Se l'impostazione vad_filter e True, il server viene avviato con
il flag --vad (Silero VAD) per filtrare il silenzio e prevenire
allucinazioni. Se il server non supporta --vad (versioni vecchie),
il fallback automatico disabilita VAD e lo gestisce lato client.

L'endpoint di trascrizione viene rilevato automaticamente tramite
una richiesta POST con un WAV minimo: /v1/audio/transcriptions
(OpenAI-compatible, supporta MP3/WAV/FLAC) oppure /inference
(endpoint originale, solo WAV).

Classes:
    WhisperBackend: Gestore del ciclo di vita di whisper-server.
"""

from __future__ import annotations

import logging
import os
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

from config.constants import SYCLDefaults, WhisperServerDefaults
from config.settings import Settings
from core.event_bus import EventBus
from core.whisper_gpu_detect import find_whisper_server, verify_sycl_binary

logger = logging.getLogger(__name__)

# Endpoint candidates in order of preference.
# /v1/audio/transcriptions supports MP3, WAV, FLAC, OGG.
# /inference (legacy) supports only WAV.
_ENDPOINTS = [
    "/v1/audio/transcriptions",
    "/inference",
]


class WhisperBackend:
    """Gestore del ciclo di vita di whisper-server con SYCL.

    Gestisce avvio, health check, rilevamento endpoint e arresto del
    processo whisper-server. L'endpoint API viene rilevato tramite
    POST con un WAV silenzioso e i successivi errori 404 attivano
    automaticamente il fallback all'endpoint alternativo.

    Attributes:
        settings: Impostazioni correnti dell'applicazione.
        server_url: URL base del server whisper.cpp.
    """

    def __init__(self, settings: Settings, project_root: Optional[Path] = None) -> None:
        """Inizializza il backend con le impostazioni date.

        Args:
            settings: Impostazioni dell'applicazione.
            project_root: Directory radice del progetto.
        """
        self._settings = settings
        self._project_root = project_root or Path(__file__).resolve().parent.parent
        self._process: Optional[subprocess.Popen[bytes]] = None
        self._server_binary: Optional[str] = None
        self._model_path: Optional[Path] = None
        self._log_file_handle: Optional[Any] = None
        self._bus = EventBus()
        # Endpoint API -- sara rilevato dopo l'avvio del server
        self._api_endpoint: str = _ENDPOINTS[0]
        # VAD lato server -- True se il server supporta --vad
        self._server_vad_enabled: bool = False
        # VAD fallback dopo errore 500 -- True se il server e stato riavviato
        # senza --vad perche VAD causava errori 500 durante l'inferenza SYCL
        self._vad_500_fallback: bool = False
        # Lock per thread safety durante il riavvio del server
        self._restart_lock = threading.Lock()

    @property
    def server_url(self) -> str:
        """URL base del server whisper.cpp."""
        return self._settings.server_url

    @property
    def is_running(self) -> bool:
        """Verifica se il server e attivo e reattivo."""
        return self._process is not None and self._process.poll() is None

    @property
    def api_endpoint(self) -> str:
        """Endpoint API di trascrizione rilevato dal server.

        Returns:
            L'endpoint API come stringa (path relativo, senza host:port).
        """
        return self._api_endpoint

    @property
    def server_vad_enabled(self) -> bool:
        """Indica se il VAD lato server e attivo.

        Returns:
            True se il server e stato avviato con --vad.
        """
        return self._server_vad_enabled

    def start(self, model_path: Path) -> None:
        """Avvia whisper-server con SYCL come processo figlio.

        Configura le variabili d'ambiente SYCL (GGML_SYCL,
        ONEAPI_DEVICE_SELECTOR, LD_LIBRARY_PATH) e avvia il server.
        Il binary compilato con SYCL usa la GPU automaticamente --
        non serve il flag --n-gpu-layers (che e solo per whisper-cli).

        Se vad_filter e True nelle impostazioni, il server viene avviato
        con il flag --vad (Silero VAD). Se il server non supporta --vad
        (ad es. versione vecchia di whisper.cpp), il fallback automatico
        riavvia il server senza VAD e affida il filtraggio del silenzio
        al rilevamento lato client.

        NOTA: non si usa --flash-attn perche su iGPU Intel Arc
        (specialmente Core Ultra 125H integrata) puo causare errori
        500 "failed to process audio" durante l'inferenza SYCL.

        Analogamente, il flag --vad (Silero VAD) puo causare lo
        stesso errore 500 su alcune configurazioni SYCL. Se cio
        accade, il server viene riavviato automaticamente senza
        --vad e il filtraggio del silenzio viene delegato al
        rilevamento lato client (RMS threshold).

        Args:
            model_path: Percorso del file modello GGUF su disco.

        Raises:
            RuntimeError: Se il binary non viene trovato, se la
                verifica SYCL fallisce, o se il server non risponde
                al health check entro il timeout.
        """
        self._model_path = model_path

        self._server_binary = find_whisper_server(self._project_root)
        if not self._server_binary:
            raise RuntimeError(
                "whisper-server non trovato. Eseguire install.sh per "
                "compilare whisper.cpp con SYCL."
            )

        if not verify_sycl_binary(self._server_binary, self._project_root):
            raise RuntimeError(
                f"whisper-server in {self._server_binary} non compilato con SYCL. "
                "Eseguire install.sh per ricompilare con il supporto SYCL."
            )

        env = self._build_env()
        use_vad = self._settings.vad_filter
        cmd = self._build_cmd(model_path, vad=use_vad)
        log_path = self._project_root / ".venv" / "whisper-server.log"

        logger.info("Avvio whisper-server: %s", " ".join(cmd))

        self._log_file_handle = open(log_path, "w", encoding="utf-8")
        self._process = subprocess.Popen(
            cmd,
            env=env,
            stdout=self._log_file_handle,
            stderr=subprocess.STDOUT,
        )

        try:
            self._wait_for_health()
        except RuntimeError:
            if use_vad:
                # Il server potrebbe non supportare --vad (versione vecchia)
                # oppure il flag causa un errore. Riavvio senza VAD.
                logger.warning(
                    "whisper-server non avviato con --vad, riprovo senza VAD..."
                )
                self._cleanup_process()
                cmd = self._build_cmd(model_path, vad=False)
                logger.info("Riavvio whisper-server senza VAD: %s", " ".join(cmd))
                self._log_file_handle = open(log_path, "w", encoding="utf-8")
                self._process = subprocess.Popen(
                    cmd,
                    env=env,
                    stdout=self._log_file_handle,
                    stderr=subprocess.STDOUT,
                )
                use_vad = False
                self._wait_for_health()
            else:
                raise

        self._server_vad_enabled = use_vad
        self._detect_api_endpoint()
        vad_status = "attivo" if use_vad else "disattivo (filtraggio lato client)"
        logger.info(
            "whisper-server pronto su %s (endpoint: %s, VAD: %s)",
            self.server_url, self._api_endpoint, vad_status,
        )

    def stop(self) -> None:
        """Arresta ordinatamente whisper-server.

        Invia terminate() e, dopo 5 secondi di attesa, kill()
        forzato se il processo non e terminato.
        """
        self._cleanup_process()
        logger.info("whisper-server fermato")

    def _cleanup_process(self) -> None:
        """Pulisce il processo whisper-server e il file di log."""
        if self._process is not None:
            logger.info("Arresto whisper-server (PID %d)...", self._process.pid)
            self._process.terminate()
            try:
                self._process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                logger.warning("whisper-server non terminato, kill forzato")
                self._process.kill()
                self._process.wait(timeout=2.0)
            self._process = None

        if self._log_file_handle and not self._log_file_handle.closed:
            self._log_file_handle.close()
            self._log_file_handle = None

    def _restart_without_vad(self) -> None:
        """Riavvia il server senza VAD dopo un errore HTTP 500.

        Su alcune configurazioni SYCL (iGPU Intel Arc, specialmente
        Core Ultra 125H integrata), il flag --vad causa errori 500
        "failed to process audio" durante l'inferenza. Questo metodo
        riavvia il server senza --vad e delega il filtraggio del
        silenzio al rilevamento lato client (RMS threshold).

        Deve essere chiamato mentre si detiene _restart_lock.
        """
        if self._vad_500_fallback or not self._server_vad_enabled:
            return

        logger.warning(
            "Riavvio whisper-server senza VAD dopo errore 500 "
            "'failed to process audio'. Il filtraggio del silenzio "
            "verra gestito lato client (RMS threshold)."
        )
        self._cleanup_process()

        cmd = self._build_cmd(self._model_path, vad=False)
        log_path = self._project_root / ".venv" / "whisper-server.log"
        env = self._build_env()

        logger.info("Riavvio whisper-server senza VAD: %s", " ".join(cmd))
        self._log_file_handle = open(log_path, "w", encoding="utf-8")
        self._process = subprocess.Popen(
            cmd,
            env=env,
            stdout=self._log_file_handle,
            stderr=subprocess.STDOUT,
        )

        self._wait_for_health()
        self._server_vad_enabled = False
        self._vad_500_fallback = True

        # Rileva endpoint dopo il riavvio
        self._detect_api_endpoint()

        logger.info(
            "whisper-server pronto su %s (endpoint: %s, VAD: disattivo "
            "-- fallback dopo errore 500, filtraggio lato client)",
            self.server_url, self._api_endpoint,
        )

    def trigger_vad_fallback(self) -> bool:
        """Riavvia il server senza VAD se VAD e attivo e non e gia stato fatto il fallback.

        Metodo pubblico per consentire al FileTranscriberThread di
        gestire errori 500 causati da --vad senza duplicare la logica
        di riavvio. Thread-safe tramite _restart_lock.

        Returns:
            True se il server e stato riavviato senza VAD, False se
            il fallback non era necessario o e gia stato applicato.
        """
        if not self._server_vad_enabled or self._vad_500_fallback:
            return False
        with self._restart_lock:
            if not self._server_vad_enabled or self._vad_500_fallback:
                return False
            self._restart_without_vad()
        return True

    def transcribe_audio(
        self,
        audio_data: bytes,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        verbose: bool = False,
    ) -> str | dict:
        """Invia audio WAV al server per la trascrizione via REST API.

        Utilizza l'endpoint API rilevato automaticamente. Se la
        richiesta riceve 404, prova automaticamente l'endpoint
        alternativo e lo memorizza per le richieste successive.

        Il parametro prompt passa il testo del segmento precedente
        a Whisper come contesto (equivalente a initial_prompt di
        OpenAI whisper). Questo e cruciale per evitare perdite di
        parole al boundary tra chunk consecutivi, perche il modello
        puo usare il contesto per decodificare correttamente le
        parole all'inizio del segmento corrente.

        Quando verbose=True, richiede response_format=verbose_json
        al server, che restituisce segmenti con word-level timestamps.
        Questo permette una rimozione precisa dell'overlap basata
        sui timestamp anziche su stime approssimative.

        Args:
            audio_data: Dati audio in formato WAV.
            language: Lingua di trascrizione (ISO 639-1).
            prompt: Testo del segmento precedente come contesto
                per condition_on_previous_text (equivalente a
                initial_prompt in OpenAI whisper).
            verbose: Se True, richiede verbose_json e restituisce
                il dict completo con segmenti e timestamps.

        Returns:
            Testo trascritto (str) se verbose=False, oppure dict
            completo con segments/timestamps se verbose=True.

        Raises:
            RuntimeError: Se il server non risponde o la richiesta fallisce.
        """
        import urllib.request
        import urllib.error
        import json

        if not self.is_running:
            raise RuntimeError("whisper-server non in esecuzione")

        # Prova l'endpoint corrente; se 404, fallback all'alternativo
        for attempt in range(2):
            endpoint = self._api_endpoint
            url = f"{self.server_url}{endpoint}"
            boundary = "----UltraTranscribrBoundary"

            is_inference = endpoint == "/inference"
            body = self._build_multipart(audio_data, language, boundary,
                                         openai_compat=not is_inference,
                                         prompt=prompt,
                                         verbose=verbose)
            headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            }

            req = urllib.request.Request(url, data=body, headers=headers, method="POST")

            try:
                with urllib.request.urlopen(req, timeout=SYCLDefaults.REQUEST_TIMEOUT_S) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    if verbose:
                        return result
                    return result.get("text", "")
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
                    self._api_endpoint = alt
                    continue

                # HTTP 500 con VAD attivo: riavvio senza VAD e riprovo.
                # Su alcune configurazioni SYCL (iGPU Intel Arc), il flag
                # --vad causa errori 500 durante l'inferenza. Il fallback
                # riavvia il server senza VAD e delega il filtraggio del
                # silenzio al rilevamento lato client (RMS threshold).
                if (exc.code == 500
                        and self._server_vad_enabled
                        and not self._vad_500_fallback):
                    logger.warning(
                        "HTTP 500 'failed to process audio' con VAD attivo "
                        "-- riavvio senza VAD e riprovo (SYCL iGPU compat)"
                    )
                    try:
                        with self._restart_lock:
                            if (self._server_vad_enabled
                                    and not self._vad_500_fallback):
                                self._restart_without_vad()
                        # Riprova la trascrizione dopo il riavvio
                        endpoint = self._api_endpoint
                        url = f"{self.server_url}{endpoint}"
                        is_inf = endpoint == "/inference"
                        body = self._build_multipart(
                            audio_data, language, boundary,
                            openai_compat=not is_inf,
                            prompt=prompt,
                            verbose=verbose,
                        )
                        headers = {
                            "Content-Type": (
                                f"multipart/form-data; boundary={boundary}"
                            ),
                        }
                        req = urllib.request.Request(
                            url, data=body, headers=headers, method="POST",
                        )
                        with urllib.request.urlopen(
                            req, timeout=SYCLDefaults.REQUEST_TIMEOUT_S
                        ) as resp:
                            result = json.loads(resp.read().decode("utf-8"))
                            if verbose:
                                return result
                            return result.get("text", "")
                    except Exception as retry_exc:
                        raise RuntimeError(
                            f"Richiesta trascrizione fallita: HTTP 500 su "
                            f"{endpoint} (anche dopo fallback VAD). "
                            f"Risposta originale: {error_body}"
                        ) from retry_exc

                raise RuntimeError(
                    f"Richiesta trascrizione fallita: HTTP {exc.code} "
                    f"su {endpoint}. Risposta: {error_body}"
                ) from exc
            except urllib.error.URLError as exc:
                raise RuntimeError(
                    f"Richiesta trascrizione fallita: {exc}"
                ) from exc

        # Non dovrebbe arrivarci mai (il loop sopra gestisce tutto)
        raise RuntimeError("Richiesta trascrizione fallita dopo tentativi endpoint")

    def _build_env(self) -> dict[str, str]:
        """Costruisce le variabili d'ambiente per SYCL.

        Imposta GGML_SYCL=1, ONEAPI_DEVICE_SELECTOR=level_zero:0,
        ZES_ENABLE_SYSMAN=1 e LD_LIBRARY_PATH con il percorso
        .venv/lib/ per le librerie condivise SYCL.

        Returns:
            Copia dell'ambiente con le variabili SYCL configurate.
        """
        env = os.environ.copy()

        # Variabili SYCL obbligatorie
        env["GGML_SYCL"] = "1"
        env["ONEAPI_DEVICE_SELECTOR"] = SYCLDefaults.ONEAPI_DEVICE_SELECTOR
        env["ZES_ENABLE_SYSMAN"] = "1"

        # LD_LIBRARY_PATH per librerie condivise nel venv e oneAPI
        ld_paths: list[str] = []

        # Librerie whisper.cpp copiate dall'installer
        venv_lib = self._project_root / ".venv" / "lib"
        if venv_lib.exists():
            ld_paths.append(str(venv_lib))

        # Librerie runtime Intel oneAPI (SYCL, MKL, TBB, ecc.)
        # Necessarie se ld.so.conf.d non e configurato o ldconfig non e stato
        # eseguito. Cerchiamo le sottodirectory versionate automaticamente.
        oneapi_root = Path("/opt/intel/oneapi")
        if oneapi_root.exists():
            for component_dir in oneapi_root.iterdir():
                if not component_dir.is_dir():
                    continue
                # Cerca la sottodirectory versionata (es. 2026.0)
                versioned_dirs = sorted(component_dir.iterdir()) if component_dir.is_dir() else []
                for vdir in versioned_dirs:
                    # Pattern: /opt/intel/oneapi/<component>/<version>/lib
                    lib_dir = vdir / "lib"
                    if lib_dir.is_dir():
                        ld_paths.append(str(lib_dir))
                    # Pattern TBB: .../lib/intel64/gcc4.8
                    tbb_lib = vdir / "lib" / "intel64" / "gcc4.8"
                    if tbb_lib.is_dir():
                        ld_paths.append(str(tbb_lib))

        current_ld = env.get("LD_LIBRARY_PATH", "")
        if ld_paths:
            new_ld = ":".join(ld_paths)
            env["LD_LIBRARY_PATH"] = (
                f"{new_ld}:{current_ld}" if current_ld else new_ld
            )

        return env

    def _build_cmd(self, model_path: Path, vad: bool = False) -> list[str]:
        """Costruisce il comando di avvio di whisper-server.

        NOTA: whisper-server NON supporta i flag di whisper-cli come
        --n-gpu-layers, -c (context) o -b (batch). Quando il binary
        e compilato con SYCL, la GPU viene usata automaticamente.
        L'offload completo su GPU e garantito dalla compilazione SYCL
        e dalla variabile d'ambiente GGML_SYCL=1.

        Il flag --vad abilita Silero VAD lato server per filtrare il
        silenzio e prevenire allucinazioni. Si usa solo --vad senza
        parametri aggiuntivi perche i nomi dei flag variano tra le
        versioni di whisper.cpp.

        NOTA: non si usa --flash-attn perche su iGPU Intel Arc
        (specialmente Core Ultra 125H integrata) puo causare errori
        500 "failed to process audio" durante l'inferenza SYCL.
        Analogamente, --vad puo causare lo stesso problema su
        alcune configurazioni; in tal caso il fallback automatico
        riavvia il server senza VAD.

        Args:
            model_path: Percorso del file modello GGUF.
            vad: Se True, aggiunge il flag --vad.

        Returns:
            Lista degli argomenti del comando.
        """
        cmd = [
            self._server_binary,
            "-m", str(model_path),
            "--port", str(self._settings.server_port),
            "--host", SYCLDefaults.HOST,
            # --split-on-word: evita che Whisper tagli parole a meta
            # ai confini dei segmenti. Senza questo flag, il modello
            # puo troncare l'output a meta parola, causando perdita
            # di parole ai boundary tra segmenti.
            "--split-on-word",
            # --no-fallback: disabilita il temperature fallback che
            # produce risultati diversi a seconda della velocita della
            # GPU. Con fallback, Whisper prova temperature crescenti
            # (0.0, 0.2, 0.4...) se la decodifica sembra pessima,
            # ma questo introduce non-determinismo: risultati diversi
            # tra GPU veloce (AC) e lenta (batteria) perche le
            # probabilita logaritmiche cambiano leggermente con la
            # velocita di inferenza, innescando o meno il fallback.
            "--no-fallback",
            # NOTA: --beam-size e --temperature NON sono flag validi
            # per whisper-server (solo per whisper-cli). Questi parametri
            # vengono passati per-request nella multipart API come campi
            # "temperature" e "beam_size" nella richiesta REST.
        ]

        if vad:
            cmd.append("--vad")

        return cmd

    def _wait_for_health(self) -> None:
        """Attende che il server risponda al health check.

        Invia richieste GET periodiche all'endpoint /health.
        Se il processo termina con codice di uscita non zero,
        estrae il log per diagnosi.

        Raises:
            RuntimeError: Se il server non risponde entro il timeout.
        """
        import urllib.request
        import urllib.error

        health_url = f"{self.server_url}/health"
        start_time = time.time()
        timeout = SYCLDefaults.HEALTH_TIMEOUT_S

        logger.info("Attesa health check su %s (timeout: %.0fs)...", health_url, timeout)

        while time.time() - start_time < timeout:
            # Verifica che il processo sia ancora vivo
            if self._process and self._process.poll() is not None:
                exit_code = self._process.returncode
                self._process = None
                log_tail = self._read_log_tail()
                raise RuntimeError(
                    f"whisper-server terminato con codice {exit_code}. "
                    f"Ultimo log: {log_tail}"
                )

            try:
                with urllib.request.urlopen(health_url, timeout=2.0) as resp:
                    if resp.status == 200:
                        return
            except (urllib.error.URLError, ConnectionError, OSError):
                pass

            time.sleep(SYCLDefaults.HEALTH_POLL_INTERVAL_S)

        self.stop()
        raise RuntimeError(
            f"whisper-server non ha risposto al health check entro {timeout}s"
        )

    def _detect_api_endpoint(self) -> None:
        """Rileva automaticamente l'endpoint API supportato dal server.

        Invia una richiesta POST con un WAV silenzioso minimo (44 byte
        header + 0 byte audio) a ciascun endpoint candidate. Il server
        rispondera con 200/400/422 se l'endpoint esiste, oppure 404
        se non esiste. GET e inaffidabile perche molti server chiudono
        la connessione su metodi non supportati.
        """
        import urllib.request
        import urllib.error

        # Costruisci un WAV silenzioso minimo (solo header, 0 campioni)
        silent_wav = self._make_silent_wav()

        for endpoint in _ENDPOINTS:
            url = f"{self.server_url}{endpoint}"
            boundary = "----ProbeBoundary"
            is_inference = endpoint == "/inference"
            body = self._build_multipart(silent_wav, None, boundary,
                                         openai_compat=not is_inference)
            headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            }
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")

            try:
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    # 200 OK = endpoint funzionante (ha trascritto il silenzio)
                    self._api_endpoint = endpoint
                    logger.info("Endpoint API rilevato: %s (POST 200)", endpoint)
                    return
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    # Endpoint inesistente -- prova il prossimo
                    logger.debug("Endpoint %s non trovato (404)", endpoint)
                    continue
                # Qualsiasi altro codice (400, 422, 500) significa che
                # l'endpoint ESISTE ma la richiesta e malformata o il file
                # e troppo piccolo. L'endpoint e valido.
                self._api_endpoint = endpoint
                logger.info(
                    "Endpoint API rilevato: %s (HTTP %d = endpoint presente)",
                    endpoint, exc.code,
                )
                return
            except (urllib.error.URLError, ConnectionError, OSError) as exc:
                logger.debug("Endpoint %s non raggiungibile: %s", endpoint, exc)
                continue

        # Se tutti i probe falliscono, prova il primo come default
        # e affida il rilevamento al retry su 404 in transcribe_audio()
        self._api_endpoint = _ENDPOINTS[0]
        logger.warning(
            "Rilevamento endpoint fallito, uso %s come default. "
            "Il rilevamento avverra automaticamente alla prima richiesta.",
            self._api_endpoint,
        )

    @staticmethod
    def _make_silent_wav() -> bytes:
        """Crea un WAV silenzioso minimo (header solo, 0 campioni).

        Returns:
            Bytes di un file WAV 16kHz mono 16-bit con 0 campioni.
        """
        sample_rate = 16000
        num_channels = 1
        sample_width = 2  # 16-bit
        data_size = 0  # nessun campione
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + data_size,
            b"WAVE",
            b"fmt ",
            16,  # chunk size
            1,   # PCM format
            num_channels,
            sample_rate,
            sample_rate * num_channels * sample_width,
            num_channels * sample_width,
            sample_width * 8,
            b"data",
            data_size,
        )
        return header

    def _read_log_tail(self, chars: int = 2000) -> str:
        """Legge le ultime righe del log del server per diagnosi.

        Args:
            chars: Numero di caratteri da leggere dalla fine del file.

        Returns:
            Ultime righe del log, o messaggio di errore.
        """
        if self._log_file_handle and not self._log_file_handle.closed:
            self._log_file_handle.close()
            self._log_file_handle = None

        log_path = self._project_root / ".venv" / "whisper-server.log"
        if not log_path.exists():
            return "(log non disponibile)"

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - chars))
                return f.read()
        except OSError:
            return "(impossibile leggere il log)"

    @staticmethod
    def _build_multipart(
        audio_data: bytes,
        language: Optional[str],
        boundary: str,
        openai_compat: bool = True,
        prompt: Optional[str] = None,
        verbose: bool = False,
    ) -> bytes:
        """Costruisce il corpo multipart/form-data per la richiesta REST.

        Campi inviati a ENTRAMBI gli endpoint (/inference e /v1/...):
          - file: audio WAV
          - language: lingua di trascrizione (opzionale)
          - prompt + initial_prompt: contesto del segmento precedente
            (inviati entrambi per compatibilita con tutte le versioni
            di whisper.cpp; alcune usano "prompt", altre "initial_prompt")
          - temperature: 0 per decodifica deterministica
          - response_format: verbose_json per timestamps, json altrimenti

        Campi solo per /v1/audio/transcriptions (openai_compat=True):
          - model: "whisper-1" (richiesto dal formato OpenAI)

        NOTA: response_format viene inviato a entrambi gli endpoint
        perche whisper.cpp lo supporta su /inference dal 2024.
        Senza verbose_json, il server non restituisce segments con
        timestamps, rendendo impossibile la rimozione precisa
        dell'overlap e causando perdita di parole ai boundary.

        Args:
            audio_data: Dati audio WAV grezzi.
            language: Lingua di trascrizione.
            boundary: Separatore multipart.
            openai_compat: Se True, include il campo model (OpenAI).
            prompt: Testo del segmento precedente come contesto
                per Whisper (initial_prompt).
            verbose: Se True, richiede verbose_json per ottenere
                word-level timestamps.

        Returns:
            Corpo della richiesta come bytes.
        """
        parts: list[bytes] = []

        # Campo file audio
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            b'Content-Disposition: form-data; name="file"; '
            b'filename="audio.wav"\r\n'
        )
        parts.append(b"Content-Type: audio/wav\r\n\r\n")
        parts.append(audio_data)
        parts.append(b"\r\n")

        # Campo lingua
        if language:
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(
                b'Content-Disposition: form-data; name="language"\r\n\r\n'
            )
            parts.append(f"{language}\r\n".encode())

        # Campo prompt (initial_prompt / condition_on_previous_text)
        # Passa il testo del segmento precedente a Whisper come contesto
        # per evitare perdite di parole al boundary tra chunk.
        # Entrambi gli endpoint (/inference e /v1/...) supportano "prompt",
        # ma alcune versioni di whisper.cpp usano "initial_prompt" per
        # l'endpoint /inference. Inviamo entrambi per compatibilita.
        if prompt and prompt.strip():
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(
                b'Content-Disposition: form-data; name="prompt"\r\n\r\n'
            )
            parts.append(f"{prompt.strip()}\r\n".encode())
            # Alias per /inference (alcune versioni usano initial_prompt)
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(
                b'Content-Disposition: form-data; name="initial_prompt"\r\n\r\n'
            )
            parts.append(f"{prompt.strip()}\r\n".encode())

        # Parametri di decodifica per-request.
        # Sia /v1/audio/transcriptions che /inference supportano questi
        # campi nella multipart API (non sono solo OpenAI-specific).
        # Temperatura 0 per decodifica deterministica (no allucinazioni).
        # CRUCIALE: temperatura 0.0 + temperature_inc 0.0 elimina il
        # temperature fallback che produce risultati diversi a seconda
        # della velocita della GPU (non-determinismo tra AC e batteria).
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            b'Content-Disposition: form-data; name="temperature"\r\n\r\n'
        )
        parts.append(b"0.0\r\n")

        # Impedisce a whisper-server di incrementare la temperatura
        # se la decodifica sembra pessima. Senza questo, il server
        # prova temperature crescenti (0.2, 0.4...) che producono
        # risultati diversi e meno accurati, specialmente ai boundary
        # dei segmenti dove il modello e meno confidente.
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            b'Content-Disposition: form-data; name="temperature_inc"\r\n\r\n'
        )
        parts.append(b"0.0\r\n")

        # Campo response_format: ENTRAMBI gli endpoint lo supportano.
        # Prima era dentro il blocco openai_compat, ma /inference
        # supporta response_format=verbose_json altrettanto bene.
        # Senza questo campo, il server restituisce solo {"text": "..."}
        # senza segments/timestamps, rendendo impossibile la rimozione
        # precisa dell'overlap basata sui timestamp e causando perdita
        # di parole ai boundary tra segmenti.
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            b'Content-Disposition: form-data; name="response_format"\r\n\r\n'
        )
        parts.append(b"verbose_json\r\n" if verbose else b"json\r\n")

        # Campi solo per /v1/audio/transcriptions (OpenAI-specific)
        if openai_compat:
            # Campo modello (formato openai)
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(
                b'Content-Disposition: form-data; name="model"\r\n\r\n'
            )
            parts.append(b"whisper-1\r\n")

        parts.append(f"--{boundary}--\r\n".encode())
        return b"".join(parts)


def _alternate_endpoint(current: str) -> str:
    """Restituisce l'endpoint alternativo a quello corrente.

    Args:
        current: L'endpoint corrente.

    Returns:
        L'endpoint alternativo.
    """
    for ep in _ENDPOINTS:
        if ep != current:
            return ep
    return current
