# core/models.py
"""Modelli dati per UltraTranscribr.

Definisce i modelli come dataclass e enum utilizzati da tutti i livelli
dell'applicazione. Indipendenti da Qt e dall'interfaccia utente.

Classes:
    StatusEnum: Codici di stato dell'applicazione.
    ProcessState: Stato di un processo audio/trascrizione.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class StatusEnum(str, Enum):
    """Codici di stato dell'applicazione / trascrizione."""

    IDLE = "idle"
    RUNNING = "running"
    BUFFERING = "buffering"
    ERROR = "error"
    LOADING_MODEL = "loading_model"
    ISOLATING_VOCALS = "isolating_vocals"
    STOPPED = "stopped"
    COMPLETED = "completed"


@dataclass(frozen=True)
class ProcessState:
    """Stato immutabile di un processo in background.

    Attributes:
        process_id: Identificativo univoco del processo.
        status: Stato corrente del processo.
        sink_name: Nome del sink audio utilizzato.
        model_size: Dimensione del modello Whisper caricato.
        error_message: Messaggio di errore, se presente.
    """

    process_id: str
    status: StatusEnum = StatusEnum.IDLE
    sink_name: Optional[str] = None
    model_size: Optional[str] = None
    error_message: Optional[str] = None
