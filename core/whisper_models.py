# core/whisper_models.py
"""Download e gestione modelli Whisper GGUF da HuggingFace.

Scarica i modelli Whisper in formato GGUF da HuggingFace e li salva
nella cache locale XDG (~/.cache/ultratranscribr/models/gguf/). Il
download avviene solo se il modello non e gia presente nella cache,
evitando riscarichi ad ogni avvio dell'applicazione.

Il modulo utilizza piu metodi di download in cascata:
  1. huggingface-hub (con supporto autenticazione)
  2. Download diretto HTTP (wget/curl via urllib)
  3. Repository alternativi se il primario fallisce

Classes:
    WhisperModelManager: Gestore download e cache modelli GGUF.
"""

from __future__ import annotations

import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from config.constants import AppMeta, WhisperServerDefaults

logger = logging.getLogger(__name__)

# Repository HuggingFace per i modelli, in ordine di preferenza
_HF_REPOS = [
    "ggerganov/whisper.cpp",
    "ggml-org/whisper-large-v3-turbo",
]

# Mapping filename per i modelli che hanno nomi diversi tra repo
_FILENAME_ALIASES = {
    "ggml-large-v3-turbo.bin": [
        "ggml-large-v3-turbo.bin",
    ],
}


class WhisperModelManager:
    """Gestore download e cache locale dei modelli Whisper GGUF.

    Scarica il modello da HuggingFace solo se non presente nella cache.
    La directory di cache e ~/.cache/ultratranscribr/models/gguf/ conforme
    alla XDG Base Directory Specification.

    Attributes:
        models_dir: Percorso della directory di cache dei modelli.
    """

    def __init__(self, models_dir: Optional[Path] = None) -> None:
        """Inizializza il gestore con la directory di cache.

        Args:
            models_dir: Percorso personalizzato per la cache.
                Se None, usa il percorso XDG predefinito.
        """
        self._models_dir = models_dir or AppMeta.MODELS_DIR

    @property
    def models_dir(self) -> Path:
        """Percorso della directory di cache dei modelli."""
        return self._models_dir

    def get_model_path(self, model_size: str) -> Path:
        """Restituisce il percorso locale del modello, scaricandolo se necessario.

        Verifica se il modello e gia presente nella cache. Se non lo e,
        avvia il download da HuggingFace. Il file viene salvato nella
        directory di cache con il nome file originale del repository.

        Args:
            model_size: Identificativo del modello (es. "large-v3-turbo").

        Returns:
            Percorso assoluto del file modello GGUF su disco.

        Raises:
            RuntimeError: Se il download fallisce per qualsiasi motivo.
        """
        filename = self._resolve_filename(model_size)
        model_path = self._models_dir / filename

        if model_path.exists() and model_path.stat().st_size > 0:
            size_mb = model_path.stat().st_size / (1024 * 1024)
            logger.info("Modello trovato in cache: %s (%.1f MB)", model_path, size_mb)
            return model_path

        logger.info("Modello non in cache, avvio download: %s", filename)
        return self._download_model(filename)

    def is_model_cached(self, model_size: str) -> bool:
        """Verifica se il modello e presente nella cache locale.

        Args:
            model_size: Identificativo del modello.

        Returns:
            True se il file modello esiste e non e vuoto.
        """
        filename = self._resolve_filename(model_size)
        model_path = self._models_dir / filename
        return model_path.exists() and model_path.stat().st_size > 0

    def _resolve_filename(self, model_size: str) -> str:
        """Risolve il nome file GGUF a partire dall'identificativo modello.

        Mappa l'identificativo del modello (es. "large-v3-turbo") al nome
        file GGUF corrispondente nel repository HuggingFace.

        Args:
            model_size: Identificativo del modello.

        Returns:
            Nome file GGUF (es. "ggml-large-v3-turbo.bin").
        """
        filename_map = {
            "tiny": "ggml-tiny.bin",
            "tiny.en": "ggml-tiny.en.bin",
            "base": "ggml-base.bin",
            "base.en": "ggml-base.en.bin",
            "small": "ggml-small.bin",
            "small.en": "ggml-small.en.bin",
            "medium": "ggml-medium.bin",
            "medium.en": "ggml-medium.en.bin",
            "large-v3": "ggml-large-v3.bin",
            "large-v3-turbo": "ggml-large-v3-turbo.bin",
        }
        return filename_map.get(model_size, WhisperServerDefaults.MODEL_FILENAME)

    def _download_model(self, filename: str) -> Path:
        """Scarica il modello GGUF con multiple strategie di fallback.

        Strategie in ordine:
        1. huggingface-hub (supporta autenticazione e resume)
        2. Download diretto HTTP via urllib (da repository primario)
        3. Download diretto HTTP (da repository alternativi)

        Args:
            filename: Nome file del modello nel repository HuggingFace.

        Returns:
            Percorso locale del modello scaricato.

        Raises:
            RuntimeError: Se il download fallisce con tutti i metodi.
        """
        self._models_dir.mkdir(parents=True, exist_ok=True)

        errors: list[str] = []

        # Nomi file alternativi (per repo che usano nomi diversi)
        filenames_to_try = _FILENAME_ALIASES.get(filename, [filename])

        # Strategia 1: huggingface-hub (supporta autenticazione)
        result = self._try_hf_hub_download(filenames_to_try, errors)
        if result is not None:
            return result

        # Strategia 2: Download diretto HTTP
        result = self._try_direct_download(filenames_to_try, errors)
        if result is not None:
            return result

        # Tutti i metodi falliti
        error_detail = "\n".join(f"  - {e}" for e in errors)
        raise RuntimeError(
            f"Download modello fallito ({filename}). Tentativi esauriti:\n"
            f"{error_detail}\n\n"
            f"Suggerimenti:\n"
            f"  1. Autenticati su HuggingFace:\n"
            f"     .venv/bin/pip install huggingface-hub\n"
            f"     .venv/bin/huggingface-cli login\n"
            f"  2. Scarica manualmente il modello da:\n"
            f"     https://huggingface.co/ggerganov/whisper.cpp\n"
            f"     e salvalo in: {self._models_dir}/{filename}\n"
            f"  3. Esegui nuovamente install.sh per il download automatico"
        )

    def _try_hf_hub_download(
        self,
        filenames: list[str],
        errors: list[str],
    ) -> Optional[Path]:
        """Prova il download tramite huggingface-hub da tutti i repository.

        Args:
            filenames: Lista di nomi file da provare.
            errors: Lista per raccogliere i messaggi di errore.

        Returns:
            Percorso del modello scaricato, oppure None.
        """
        try:
            from huggingface_hub import hf_hub_download
        except ImportError:
            errors.append("huggingface-hub non installato")
            return None

        for repo_id in _HF_REPOS:
            for fname in filenames:
                try:
                    logger.info(
                        "Download HuggingFace: repo=%s, file=%s", repo_id, fname,
                    )
                    downloaded_path = hf_hub_download(
                        repo_id=repo_id,
                        filename=fname,
                        local_dir=str(self._models_dir),
                    )
                    result_path = Path(downloaded_path)
                    if result_path.exists() and result_path.stat().st_size > 0:
                        # Se il filename e diverso da quello target, rinomina
                        target_path = self._models_dir / filenames[0]
                        if result_path != target_path and not target_path.exists():
                            import shutil
                            shutil.copy2(result_path, target_path)
                            result_path = target_path
                        size_mb = result_path.stat().st_size / (1024 * 1024)
                        logger.info(
                            "Download completato: %s (%.1f MB)", result_path, size_mb,
                        )
                        return result_path
                except Exception as exc:
                    msg = f"hf_hub_download({repo_id}/{fname}): {exc}"
                    logger.debug(msg)
                    errors.append(msg)

        return None

    def _try_direct_download(
        self,
        filenames: list[str],
        errors: list[str],
    ) -> Optional[Path]:
        """Prova il download diretto HTTP da HuggingFace.

        Costruisce gli URL diretti per ogni repository e filename,
        e tenta il download con urllib.

        Args:
            filenames: Lista di nomi file da provare.
            errors: Lista per raccogliere i messaggi di errore.

        Returns:
            Percorso del modello scaricato, oppure None.
        """
        target_path = self._models_dir / filenames[0]

        for repo_id in _HF_REPOS:
            for fname in filenames:
                url = (
                    f"https://huggingface.co/{repo_id}"
                    f"/resolve/main/{fname}"
                )
                try:
                    logger.info(
                        "Download diretto HTTP: %s", url,
                    )
                    result = self._download_with_progress(url, target_path)
                    if result is not None:
                        return result
                except Exception as exc:
                    msg = f"HTTP download({url}): {exc}"
                    logger.debug(msg)
                    errors.append(msg)

        return None

    def _download_with_progress(
        self,
        url: str,
        target_path: Path,
    ) -> Optional[Path]:
        """Scarica un file con progress logging e resume parziale.

        Supporta il resume di download interrotti tramite header Range.
        Il file temporaneo ha suffisso .part e viene rinominato al
        completamento.

        Args:
            url: URL del file da scaricare.
            target_path: Percorso locale di destinazione.

        Returns:
            Percorso del file scaricato, oppure None se fallito.
        """
        part_path = Path(str(target_path) + ".part")
        existing_size = 0

        if part_path.exists():
            existing_size = part_path.stat().st_size
            logger.info("Ripresa download parziale: %d byte esistenti", existing_size)

        try:
            req = urllib.request.Request(url)
            if existing_size > 0:
                req.add_header("Range", f"bytes={existing_size}-")

            with urllib.request.urlopen(req, timeout=30) as resp:
                # Risposta 206 Partial Content: il server onora il resume e
                # restituisce solo i byte dal punto richiesto. Possiamo
                # aprire il file in modalita append.
                # Risposta 200 OK: il server ignora l'header Range e
                # restituisce l'intero file. Riaprire in append corromperebbe
                # il file (duplicando i byte gia presenti); dobbiamo
                # ricominciare da capo con modalita write e azzerare
                # existing_size nel conteggio del progresso.
                is_partial = resp.status == 206
                mode = "ab" if (is_partial and existing_size > 0) else "wb"
                if not is_partial:
                    if existing_size > 0:
                        logger.info(
                            "Server non supporta Range (HTTP %d), "
                            "ricomincio il download da capo",
                            resp.status,
                        )
                    existing_size = 0

                total_size = resp.headers.get("Content-Length")
                if total_size:
                    total_size = int(total_size) + existing_size

                with open(part_path, mode) as f:
                    downloaded = existing_size
                    last_report = 0
                    chunk_size = 1024 * 1024  # 1 MB

                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                        # Log progress ogni 100 MB o al 10%
                        if total_size:
                            pct = int(downloaded * 100 / total_size)
                            if pct >= last_report + 10:
                                size_mb = downloaded / (1024 * 1024)
                                total_mb = total_size / (1024 * 1024)
                                logger.info(
                                    "  Progresso: %.0f/%.0f MB (%d%%)",
                                    size_mb, total_mb, pct,
                                )
                                last_report = pct

            # Verifica il file scaricato
            if part_path.exists() and part_path.stat().st_size > 1_000_000:
                part_path.rename(target_path)
                size_mb = target_path.stat().st_size / (1024 * 1024)
                logger.info("Download completato: %s (%.1f MB)", target_path, size_mb)
                return target_path

            logger.warning("File scaricato troppo piccolo, probabile errore")
            part_path.unlink(missing_ok=True)

        except urllib.error.HTTPError as exc:
            logger.debug("HTTP error %d per %s", exc.code, url)
            if exc.code == 401:
                logger.debug("Repo richiede autenticazione: %s", url)
            raise
        except urllib.error.URLError as exc:
            logger.debug("URL error per %s: %s", url, exc)
            raise
        except Exception as exc:
            logger.debug("Errore download %s: %s", url, exc)
            raise

        return None
