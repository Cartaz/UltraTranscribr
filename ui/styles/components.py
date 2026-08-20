# ui/styles/components.py
"""Funzioni di utilita per lo stile dei componenti UI.

Fornisce helper per la mappatura degli stati ai colori del tema
e per la generazione di etichette leggibili. Tutti i valori
cromatici provengono da config/theme.py.

Functions:
    status_color: Restituisce il colore hex per uno stato dato.
    status_label: Restituisce un'etichetta leggibile per uno stato.
"""

from __future__ import annotations

from config.theme import ThemeColors


def status_color(status: str) -> str:
    """Restituisce il colore hex del tema per un dato stato.

    Args:
        status: Stringa dello stato (es. "running", "error", "draining").

    Returns:
        Colore hex dal tema, o STATUS_STOPPED come fallback.
    """
    mapping: dict[str, str] = {
        "running": ThemeColors.STATUS_RUNNING,
        "buffering": ThemeColors.STATUS_BUFFERING,
        "idle": ThemeColors.STATUS_STOPPED,
        "error": ThemeColors.STATUS_ERROR,
        "loading_model": ThemeColors.STATUS_LOADING,
        "isolating_vocals": ThemeColors.STATUS_LOADING,
        "stopped": ThemeColors.STATUS_STOPPED,
        "completed": ThemeColors.STATUS_RUNNING,
        "draining": ThemeColors.STATUS_PAUSED,
    }
    return mapping.get(status.lower(), ThemeColors.STATUS_STOPPED)


def status_label(status: str) -> str:
    """Restituisce un'etichetta leggibile in italiano per uno stato.

    Args:
        status: Stringa dello stato (es. "running", "error", "draining").

    Returns:
        Etichetta leggibile, o lo stato stesso come fallback.
    """
    mapping: dict[str, str] = {
        "running": "Trascrizione in corso",
        "buffering": "Buffering — recupero in corso",
        "idle": "In attesa",
        "error": "Errore",
        "loading_model": "Caricamento modello…",
        "isolating_vocals": "Isolamento voce (Demucs)…",
        "stopped": "Fermato",
        "completed": "Completato",
        "draining": "Svuotamento buffer…",
    }
    return mapping.get(status.lower(), status)
