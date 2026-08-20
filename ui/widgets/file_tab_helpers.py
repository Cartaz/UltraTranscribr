# ui/widgets/file_tab_helpers.py
"""Costanti e funzioni di supporto per FileTab.

Contiene configurazioni fisse, mappe di traduzione, funzioni
ausiliarie e costruttori di widget UI utilizzati dalla scheda
File. Estratti per rispettare il limite di 300 righe per modulo.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QHBoxLayout,
    QLabel, QSizePolicy, QWidget,
)
from config.theme import ThemeColors
from ui.widgets.action_button import ActionButton
from ui.widgets.status_indicator import StatusIndicator

# -- Costanti -----------------------------------------------------------

LANG_MAP: dict[str, str] = {"en": "English", "it": "Italiano"}
"""Mappa codice lingua -> etichetta localizzata."""
FILE_FILTER: str = "File audio (*.mp3 *.wav);;Tutti i file (*)"
"""Filtro per QFileDialog nella selezione file audio."""
STATUS_STYLE: str = (
    f"color: {ThemeColors.TEXT_SECONDARY}; font-size: 12px; "
    f"background: transparent; border: none;"
)
"""Stile CSS riutilizzato per le etichette di stato."""
_STATUS_TO_INDICATOR: dict[str, StatusIndicator.State] = {
    "running": StatusIndicator.State.RUNNING, "idle": StatusIndicator.State.IDLE,
    "error": StatusIndicator.State.ERROR, "loading_model": StatusIndicator.State.LOADING,
    "isolating_vocals": StatusIndicator.State.LOADING,
    "stopped": StatusIndicator.State.STOPPED, "completed": StatusIndicator.State.COMPLETED,
}

# -- Tooltip costanti ---------------------------------------------------

_MUSIC_TIP = (
    "Attiva per file con musica o canzoni.\n"
    "Disabilita il VAD e isola la voce con Demucs\n"
    "per ottenere risultati ottimali dal materiale musicale."
)
_MUSIC_TIP_NO_DEMUCS = (
    "Attiva per file con musica o canzoni.\n"
    "Disabilita il VAD per non eliminare il canto.\n\n"
    "Per isolare anche la voce dalla musica:\n"
    "pip install demucs"
)

# -- Funzioni di conversione stato --------------------------------------

def status_to_indicator_state(status: str) -> StatusIndicator.State:
    """Converte il nome di una fase nello stato del StatusIndicator.

    Args:
        status: Nome della fase (es. ``"running"``, ``"completed"``).

    Returns:
        Lo stato ``StatusIndicator.State`` corrispondente oppure ``IDLE``.
    """
    return _STATUS_TO_INDICATOR.get(status, StatusIndicator.State.IDLE)


def error_status_style() -> str:
    """Restituisce lo stile CSS per un messaggio di errore nello stato."""
    return f"color: {ThemeColors.STATUS_ERROR};"


# -- Stili riutilizzabili -----------------------------------------------

def file_label_style(has_file: bool) -> str:
    """Restituisce lo stile CSS per l'etichetta del file selezionato.

    Args:
        has_file: Se un file e stato selezionato.
    """
    c = ThemeColors.TEXT_PRIMARY if has_file else ThemeColors.TEXT_SECONDARY
    return (
        f"color: {c}; font-family: '{ThemeColors.FONT_FAMILY_MONO}'; "
        f"font-size: 12px; padding: 4px; background: {ThemeColors.BG_SURFACE}; "
        f"border: 1px solid {ThemeColors.BORDER}; border-radius: 4px;"
    )


# -- Costruttori di widget UI -------------------------------------------

def build_file_row() -> tuple[QHBoxLayout, QLabel, ActionButton]:
    """Crea la riga di selezione file. Returns: (layout, file_label, browse_btn)."""
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(QLabel("File:"))
    file_label = QLabel("Nessun file selezionato")
    file_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    file_label.setStyleSheet(file_label_style(False))
    row.addWidget(file_label)
    browse_btn = ActionButton("Sfoglia", "Ctrl+O", style_variant="neutral", show_indicator=False)
    row.addWidget(browse_btn)
    return row, file_label, browse_btn


def build_lang_music_row(
    initial_lang: str = "en",
    demucs_available: bool = True,
) -> tuple[QHBoxLayout, QComboBox, QCheckBox]:
    """Crea la riga lingua + musica.

    Returns: (layout, lang_combo, music_checkbox).
    """
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(QLabel("Lingua:"))
    lang_combo = QComboBox()
    for code, label in LANG_MAP.items():
        lang_combo.addItem(label, code)
    lang_idx = lang_combo.findData(initial_lang)
    if lang_idx >= 0:
        lang_combo.setCurrentIndex(lang_idx)
    lang_combo.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    row.addWidget(lang_combo)

    music_checkbox = QCheckBox("Musica")
    if demucs_available:
        music_checkbox.setToolTip(_MUSIC_TIP)
    else:
        music_checkbox.setToolTip(_MUSIC_TIP_NO_DEMUCS)
    row.addWidget(music_checkbox)

    return row, lang_combo, music_checkbox


def build_actions_grid() -> tuple[
    QGridLayout, ActionButton, ActionButton, ActionButton, ActionButton
]:
    """Crea la griglia azioni 2x2.

    Layout: Riga 0 = Trascrivi (Orange Glow) + Cancella (Orange Text);
    Riga 1 = Salva Testo + Ferma.
    Returns: (grid, transcribe_btn, clear_btn, save_btn, stop_btn).
    """
    grid = QGridLayout()
    grid.setSpacing(10)
    transcribe_btn = ActionButton(
        "Trascrivi", "Ctrl+R", "transcribeButton",
        style_variant="orange_glow", show_indicator=True,
    )
    clear_btn = ActionButton(
        "Cancella", "Ctrl+D", "clearButton",
        style_variant="orange_text", show_indicator=True,
    )
    save_btn = ActionButton(
        "Salva Testo", "Ctrl+Shift+S", "saveButton",
        style_variant="neutral", show_indicator=False,
    )
    stop_btn = ActionButton(
        "Ferma", "Ctrl+S", "stopButton",
        style_variant="neutral", show_indicator=True,
    )
    stop_btn.setEnabled(False)
    save_btn.setEnabled(False)
    # Riga 0: Trascrivi + Cancella
    grid.addWidget(transcribe_btn, 0, 0)
    grid.addWidget(clear_btn, 0, 1)
    # Riga 1: Salva Testo + Ferma
    grid.addWidget(save_btn, 1, 0)
    grid.addWidget(stop_btn, 1, 1)
    for col in range(2):
        grid.setColumnStretch(col, 1)
    grid.setRowMinimumHeight(1, 32)
    return grid, transcribe_btn, clear_btn, save_btn, stop_btn


def build_status_bar() -> tuple[QWidget, StatusIndicator, QLabel, QLabel, QLabel]:
    """Crea la barra di stato. Returns: (row_widget, indicator, status_label, progress_label, segment_label)."""
    row = QWidget()
    row.setObjectName("statusBar")
    hl = QHBoxLayout(row)
    hl.setContentsMargins(8, 2, 8, 2)
    hl.setSpacing(12)
    indicator = StatusIndicator()
    hl.addWidget(indicator)
    status_label = QLabel("Pronto")
    status_label.setStyleSheet(STATUS_STYLE)
    hl.addWidget(status_label)
    hl.addStretch()
    progress_label = QLabel("")
    progress_label.setStyleSheet(STATUS_STYLE)
    progress_label.setMinimumWidth(90)
    hl.addWidget(progress_label)
    segment_label = QLabel("")
    segment_label.setStyleSheet(STATUS_STYLE)
    hl.addWidget(segment_label)
    return row, indicator, status_label, progress_label, segment_label
