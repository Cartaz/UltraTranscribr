# ui/widgets/file_tab_helpers.py
"""Helper della scheda File con controlli neumorfici senza cambio layout."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QHBoxLayout,
    QLabel, QSizePolicy, QWidget,
)

from config.theme import ThemeColors
from ui.widgets.action_button import ActionButton
from ui.widgets.neumorphic import NeumorphicComboBox
from ui.widgets.status_indicator import StatusIndicator

LANG_MAP: dict[str, str] = {
    "en": "English",
    "it": "Italiano",
}
FILE_FILTER: str = "File audio (*.mp3 *.wav);;Tutti i file (*)"

STATUS_STYLE: str = (
    f"color: {ThemeColors.TEXT_SECONDARY}; "
    f"font-size: 12px; "
    f"background: transparent; border: none;"
)

_STATUS_TO_INDICATOR: dict[str, StatusIndicator.State] = {
    "running": StatusIndicator.State.RUNNING,
    "idle": StatusIndicator.State.IDLE,
    "error": StatusIndicator.State.ERROR,
    "loading_model": StatusIndicator.State.LOADING,
    "isolating_vocals": StatusIndicator.State.LOADING,
    "stopped": StatusIndicator.State.STOPPED,
    "completed": StatusIndicator.State.COMPLETED,
}

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


def status_to_indicator_state(
    status: str,
) -> StatusIndicator.State:
    return _STATUS_TO_INDICATOR.get(
        status, StatusIndicator.State.IDLE
    )


def error_status_style() -> str:
    return f"color: {ThemeColors.STATUS_ERROR};"


def file_label_style(has_file: bool) -> str:
    c = (
        ThemeColors.TEXT_PRIMARY
        if has_file
        else ThemeColors.TEXT_SECONDARY
    )
    return (
        f"color: {c}; "
        f"font-family: '{ThemeColors.FONT_FAMILY_MONO}'; "
        f"font-size: 12px; padding: 4px; "
        f"background: {ThemeColors.BG_SURFACE}; "
        f"border-top: 1px solid {ThemeColors.BORDER_DARK}; "
        f"border-left: 1px solid {ThemeColors.BORDER_DARK}; "
        f"border-right: 1px solid {ThemeColors.BORDER_LIGHT}; "
        f"border-bottom: 1px solid {ThemeColors.BORDER_LIGHT}; "
        f"border-radius: 6px;"
    )


def build_file_row() -> tuple[
    QHBoxLayout, QLabel, ActionButton
]:
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(QLabel("File:"))

    file_label = QLabel("Nessun file selezionato")
    file_label.setSizePolicy(
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.Fixed,
    )
    file_label.setStyleSheet(file_label_style(False))
    row.addWidget(file_label)

    browse_btn = ActionButton(
        "Sfoglia",
        "Ctrl+O",
        style_variant="neutral",
        show_indicator=False,
    )
    row.addWidget(browse_btn)
    return row, file_label, browse_btn


def build_lang_music_row(
    initial_lang: str = "en",
    demucs_available: bool = True,
) -> tuple[QHBoxLayout, NeumorphicComboBox, QCheckBox]:
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(QLabel("Lingua:"))

    lang_combo = NeumorphicComboBox()
    for code, label in LANG_MAP.items():
        lang_combo.addItem(label, code)
    lang_idx = lang_combo.findData(initial_lang)
    if lang_idx >= 0:
        lang_combo.setCurrentIndex(lang_idx)
    lang_combo.setSizePolicy(
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.Fixed,
    )
    row.addWidget(lang_combo)

    music_checkbox = QCheckBox("Musica")
    music_checkbox.setToolTip(
        _MUSIC_TIP
        if demucs_available
        else _MUSIC_TIP_NO_DEMUCS
    )
    row.addWidget(music_checkbox)

    return row, lang_combo, music_checkbox


def build_actions_grid() -> tuple[
    QGridLayout,
    ActionButton,
    ActionButton,
    ActionButton,
    ActionButton,
]:
    grid = QGridLayout()
    grid.setSpacing(10)

    transcribe_btn = ActionButton(
        "Trascrivi",
        "Ctrl+R",
        "transcribeButton",
        style_variant="orange_glow",
        show_indicator=True,
    )
    clear_btn = ActionButton(
        "Cancella",
        "Ctrl+D",
        "clearButton",
        style_variant="orange_text",
        show_indicator=True,
    )
    save_btn = ActionButton(
        "Salva Testo",
        "Ctrl+Shift+S",
        "saveButton",
        style_variant="neutral",
        show_indicator=False,
    )
    stop_btn = ActionButton(
        "Ferma",
        "Ctrl+S",
        "stopButton",
        style_variant="neutral",
        show_indicator=True,
    )

    stop_btn.setEnabled(False)
    save_btn.setEnabled(False)

    grid.addWidget(transcribe_btn, 0, 0)
    grid.addWidget(clear_btn, 0, 1)
    grid.addWidget(save_btn, 1, 0)
    grid.addWidget(stop_btn, 1, 1)

    for col in range(2):
        grid.setColumnStretch(col, 1)
    grid.setRowMinimumHeight(1, 32)

    return (
        grid,
        transcribe_btn,
        clear_btn,
        save_btn,
        stop_btn,
    )


def build_status_bar() -> tuple[
    QWidget,
    StatusIndicator,
    QLabel,
    QLabel,
    QLabel,
]:
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

    return (
        row,
        indicator,
        status_label,
        progress_label,
        segment_label,
    )
