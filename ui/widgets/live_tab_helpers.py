# ui/widgets/live_tab_helpers.py
"""Costanti e funzioni di supporto per LiveTab.

Contiene mappe di traduzione stato->indicatore, funzioni ausiliarie
per lo stile e costruttori di widget UI utilizzati dalla scheda Live.
Estratti per rispettare il limite di 300 righe per modulo.
"""
from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QWidget

from config.theme import ThemeColors
from ui.widgets.action_button import ActionButton
from ui.widgets.status_indicator import StatusIndicator

# -- Mappa stati -> indicatore visivo -------------------------------------

STATUS_TO_INDICATOR: dict[str, StatusIndicator.State] = {
    "running": StatusIndicator.State.RUNNING,
    "buffering": StatusIndicator.State.BUFFERING,
    "idle": StatusIndicator.State.IDLE,
    "error": StatusIndicator.State.ERROR,
    "loading_model": StatusIndicator.State.LOADING,
    "stopped": StatusIndicator.State.STOPPED,
    "draining": StatusIndicator.State.PAUSED,
    "completed": StatusIndicator.State.COMPLETED,
}
"""Mappa codice stato -> stato del StatusIndicator."""

STATUS_LABEL_STYLE: str = (
    f"color: {ThemeColors.TEXT_SECONDARY}; font-size: 12px; "
    f"background: transparent; border: none;"
)
"""Stile CSS riutilizzato per le etichette di stato."""

ERROR_STATUS_STYLE: str = f"color: {ThemeColors.STATUS_ERROR};"
"""Stile CSS per i messaggi di errore nella barra di stato."""


# -- Funzioni di supporto -------------------------------------------------

def status_to_indicator_state(status: str) -> StatusIndicator.State:
    """Converte il nome di uno stato nello stato del StatusIndicator.

    Args:
        status: Nome dello stato (es. ``"running"``, ``"draining"``).

    Returns:
        Lo stato ``StatusIndicator.State`` corrispondente oppure ``IDLE``.
    """
    return STATUS_TO_INDICATOR.get(status, StatusIndicator.State.IDLE)


def stat_label_style(color: str = ThemeColors.TEXT_SECONDARY) -> str:
    """Restituisce lo stile CSS per le label della barra di stato.

    Args:
        color: Colore del testo (default: TEXT_SECONDARY).

    Returns:
        Stringa QSS per lo stile della label.
    """
    return (f"color: {color}; font-size: 12px; "
            f"background: transparent; border: none;")


def buffer_level_style(level: int) -> tuple[str, str]:
    """Restituisce il colore e lo stile per l'etichetta del livello buffer.

    Args:
        level: Livello del buffer in percentuale (0-100+).

    Returns:
        Tupla (colore, stile_qss) per la label del buffer.
    """
    if level > 100:
        color = ThemeColors.STATUS_ERROR
    elif level > 50:
        color = ThemeColors.STATUS_BUFFERING
    else:
        color = ThemeColors.STATUS_RUNNING
    return color, stat_label_style(color)


# -- Costruttori di widget UI -------------------------------------------

def build_actions_grid() -> tuple[
    QGridLayout, ActionButton, ActionButton,
    ActionButton, ActionButton, ActionButton,
]:
    """Crea la griglia azioni per la scheda Live conforme allo screenshot.

    Layout (5 azioni, griglia 3+2):
      Riga 0: Avvia (Orange Glow) + Fine Audio (Neutral) + Aggiorna (Orange Glow)
      Riga 1: Cancella (Orange Text) + Ferma (Neutral)

    Returns:
        (grid, start_btn, stop_listening_btn, stop_btn, clear_btn, refresh_btn)
    """
    grid = QGridLayout()
    grid.setSpacing(10)

    start_btn = ActionButton(
        "Avvia", "Ctrl+R", "startButton",
        style_variant="orange_glow", show_indicator=True,
    )
    stop_listening_btn = ActionButton(
        "Fine Audio", "Ctrl+E", "stopListeningButton",
        style_variant="neutral", show_indicator=True,
    )
    refresh_btn = ActionButton(
        "Aggiorna", "F5", "refreshButton",
        style_variant="orange_glow", show_indicator=False,
    )
    clear_btn = ActionButton(
        "Cancella", "Ctrl+D", "clearButton",
        style_variant="orange_text", show_indicator=True,
    )
    stop_btn = ActionButton(
        "Ferma", "Ctrl+S", "stopButton",
        style_variant="neutral", show_indicator=True,
    )
    stop_btn.setEnabled(False)
    stop_listening_btn.setEnabled(False)

    grid.addWidget(start_btn, 0, 0)
    grid.addWidget(stop_listening_btn, 0, 1)
    grid.addWidget(refresh_btn, 0, 2)
    grid.addWidget(clear_btn, 1, 0)
    grid.addWidget(stop_btn, 1, 1)

    for col in range(3):
        grid.setColumnStretch(col, 1)
    grid.setRowMinimumHeight(1, 32)

    return (grid, start_btn, stop_listening_btn,
            stop_btn, clear_btn, refresh_btn)


def build_status_bar() -> tuple[
    QWidget, StatusIndicator, QLabel, QLabel, QLabel,
]:
    """Crea la barra di stato per la scheda Live.

    Returns:
        (row_widget, indicator, status_label, buffer_label, stats_label)
    """
    row = QWidget()
    row.setObjectName("statusBar")
    hl = QHBoxLayout(row)
    hl.setContentsMargins(8, 2, 8, 2)
    hl.setSpacing(12)
    indicator = StatusIndicator()
    hl.addWidget(indicator)
    status_label = QLabel("In attesa")
    status_label.setStyleSheet(STATUS_LABEL_STYLE)
    hl.addWidget(status_label)
    hl.addStretch()
    hl.addWidget(QLabel("Buffer:"))
    buffer_label = QLabel("0%")
    buffer_label.setMinimumWidth(35)
    buffer_label.setStyleSheet(stat_label_style(ThemeColors.STATUS_RUNNING))
    hl.addWidget(buffer_label)
    stats_label = QLabel("")
    stats_label.setObjectName("statsLabel")
    hl.addWidget(stats_label)
    return row, indicator, status_label, buffer_label, stats_label
