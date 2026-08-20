"""Isolamento vocale da file audio tramite Demucs.

Usa il modello Demucs (htdemucs) per separare la traccia vocale
dalla strumentazione musicale.  Questo migliora drasticamente
la qualita della trascrizione Whisper per le canzoni, perche
Whisper e addestrato su parlato e confonde la musica con rumore.

L'isolamento e opzionale e viene attivato solo quando l'utente
seleziona "Isola voce" nella scheda File.  Se Demucs non e
installato, l'operazione viene saltata con un avviso.

Supporta il reporting del progresso tramite un callback opzionale
(progress_callback) che riceve un valore intero 0-100.

Strategie di import (in ordine di preferenza):
  1. demucs.api.Separator (API Python pulita)
  2. demucs.pretrained + demucs.apply (API basso livello)
  3. demucs.separate CLI con monkeypatch di torchaudio

Public API:
    isolate_vocals: Estrae la traccia vocale da un file audio.
    is_demucs_available: Verifica se Demucs e installato e funzionante.
    cleanup_vocals: Rimuove il file vocale temporaneo e la directory.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class _DemucsCache:
    """Cache singleton per lo stato di disponibilita di Demucs.

    Incapsula i flag di disponibilita e strategia per evitare
    variabili mutabili a livello di modulo.

    Attributes:
        _available: None finche non verificato, poi True/False.
        _strategy: None finche non verificato, poi nome strategia.
    """

    def __init__(self) -> None:
        self._available: Optional[bool] = None
        self._strategy: Optional[str] = None

    @property
    def available(self) -> Optional[bool]:
        """Restituisce lo stato di disponibilita (None = non verificato)."""
        return self._available

    @property
    def strategy(self) -> Optional[str]:
        """Restituisce la strategia corrente (None = non verificato)."""
        return self._strategy

    def set(self, available: bool, strategy: str) -> None:
        """Imposta disponibilita e strategia.

        Args:
            available: True se Demucs e utilizzabile.
            strategy: Nome della strategia rilevata.
        """
        self._available = available
        self._strategy = strategy


_CACHE = _DemucsCache()


def is_demucs_available() -> bool:
    """Verifica se la libreria Demucs e installata e utilizzabile.

    Il risultato viene memorizzato nella cache dopo la prima chiamata.

    Returns:
        True se Demucs e disponibile, False altrimenti.
    """
    if _CACHE.available is None:
        available, strategy = _check_demucs()
        _CACHE.set(available, strategy)
        if available:
            logger.info("Demucs disponibile — strategia: %s", strategy)
        else:
            logger.warning("Demucs NON disponibile — isolamento vocale disabilitato")
    return bool(_CACHE.available)


def isolate_vocals(
    input_path: str,
    model_name: str = "htdemucs",
    device: str = "cpu",
    stop_event: Optional[object] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> Optional[str]:
    """Estrae la traccia vocale da un file audio usando Demucs.

    Args:
        input_path: Percorso del file audio di input.
        model_name: Nome del modello Demucs (default: htdemucs).
        device: Dispositivo di calcolo (default: cpu).
        stop_event: Evento per interrompere l'operazione.
        progress_callback: Callback che riceve il progresso (0-100).

    Returns:
        Percorso del file WAV vocale isolato, oppure None se fallito.
    """
    if not is_demucs_available():
        logger.warning(
            "Demucs non installato o non funzionante — "
            "isolamento vocale non disponibile. "
            "Installa con: pip install demucs"
        )
        return None

    input_file = Path(input_path)
    if not input_file.exists():
        logger.error("File non trovato: %s", input_path)
        return None

    strategy = _CACHE.strategy

    try:
        logger.info(
            "Isolamento vocale con Demucs — modello: %s, device: %s, strategia: %s",
            model_name, device, strategy,
        )
        logger.info("File input: %s", input_path)

        if device == "cpu":
            logger.info(
                "NOTA: l'isolamento vocale su CPU puo richiedere 2-5 minuti "
                "per ogni minuto di audio. Attendi senza chiudere il programma."
            )

        if progress_callback:
            progress_callback(0)

        from core.vocal_isolator_io import (
            _isolate_api,
            _isolate_cli,
            _isolate_lowlevel,
        )

        if strategy == "api":
            return _isolate_api(
                input_path, model_name, device, stop_event, progress_callback,
            )
        if strategy == "lowlevel":
            return _isolate_lowlevel(
                input_path, model_name, device, stop_event, progress_callback,
            )
        if strategy == "cli":
            return _isolate_cli(
                input_path, model_name, device, stop_event, progress_callback,
            )
        logger.error("Strategia Demucs sconosciuta: %s", strategy)
        return None

    except Exception as exc:
        logger.error(
            "Errore durante l'isolamento vocale (strategia %s): %s: %s",
            strategy, type(exc).__name__, exc,
        )
        return None


def cleanup_vocals(vocal_path: Optional[str]) -> None:
    """Rimuove il file vocale temporaneo e la sua directory.

    Args:
        vocal_path: Percorso del file vocale temporaneo, oppure None.
    """
    if vocal_path is None:
        return
    try:
        p = Path(vocal_path)
        if p.exists():
            p.unlink()
            parent = p.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
            logger.info("File vocale temporaneo rimosso: %s", vocal_path)
    except OSError as exc:
        logger.warning("Impossibile rimuovere il file vocale temporaneo: %s", exc)


def _check_demucs() -> tuple[bool, str]:
    """Verifica se Demucs e installato e determina la strategia da usare.

    Returns:
        Tupla (disponibile, nome_strategia).
    """
    # Strategia 1: demucs.api.Separator
    try:
        import demucs.api  # noqa: F401
        return True, "api"
    except ImportError as exc:
        logger.debug("demucs.api non disponibile: %s", exc)

    # Strategia 2: demucs.pretrained + demucs.apply
    try:
        import demucs.apply  # noqa: F401
        import demucs.pretrained  # noqa: F401
        return True, "lowlevel"
    except ImportError as exc:
        logger.debug("demucs.pretrained/apply non disponibile: %s", exc)

    # Strategia 3: demucs.separate CLI
    try:
        from demucs.separate import main as _cli  # noqa: F401
        return True, "cli"
    except ImportError as exc:
        logger.debug("demucs.separate non disponibile: %s", exc)

    # Import generico per loggare l'errore reale
    try:
        import demucs  # noqa: F401
        logger.warning(
            "demucs importato ma nessuna API funzionante trovata. "
            "Possibile problema di compatibilita."
        )
    except ImportError as exc:
        logger.warning("import demucs fallito: %s: %s", type(exc).__name__, exc)

    return False, "none"
