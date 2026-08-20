# ui/widgets/file_tab.py
"""Scheda File — trascrizione di file audio (.mp3, .wav).

Supporta sia file audio puliti che canzoni da cui estrarre il testo.
In modalita musica, il VAD viene disabilitato e l'isolamento vocale
con Demucs e disponibile per separare la voce dalla musica.

La progressione viene mostrata come testo nella barra di stato
(come "Progresso: 45/100"), nello stesso punto in cui la scheda
Live mostra Buffer e statistiche.

Classes:
    FileTab: Scheda per la trascrizione di file audio.
"""

from __future__ import annotations

import logging
from pathlib import Path
from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QFileDialog, QMessageBox, QTextEdit, QSizePolicy, QVBoxLayout, QWidget,
    QLabel, QHBoxLayout,
)

from config.theme import ThemeColors
from core.app_controller import AppController
from core.vocal_isolator import is_demucs_available
from ui.styles.components import status_label
from ui.widgets.card import Card
from ui.widgets.file_tab_helpers import (
    FILE_FILTER, STATUS_STYLE,
    build_actions_grid, build_file_row, build_lang_music_row,
    error_status_style, file_label_style,
    status_to_indicator_state,
)
from ui.widgets.status_indicator import StatusIndicator

logger = logging.getLogger(__name__)


class FileTab(QWidget):
    """Scheda per la trascrizione di file audio.

    Args:
        controller: Controller principale dell'applicazione.
        parent: Widget genitore.
    """

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._file_path: str | None = None
        self._full_text: str = ""
        self._segment_count: int = 0
        self._demucs_available: bool = is_demucs_available()
        self._current_phase: str = "idle"
        self._current_percent: int = 0
        self._setup_ui()

    # -- Costruzione UI --------------------------------------------------

    def _setup_ui(self) -> None:
        """Costruisce l'interfaccia della scheda."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._add_config_card(layout)
        self._add_actions_card(layout)
        self._add_text_area(layout)
        self._add_status_bar(layout)

    def _add_config_card(self, layout: QVBoxLayout) -> None:
        """Aggiunge la card di configurazione."""
        card = Card("CONFIGURAZIONE FILE", self)
        content = card.content_layout()
        # Riga file
        file_row, self._file_label, self._browse_btn = build_file_row()
        self._browse_btn.action_requested.connect(self._on_browse)
        content.addLayout(file_row)
        # Riga lingua + musica
        lang_music_row, self._lang_combo, self._music_checkbox = build_lang_music_row(
            initial_lang=self._controller.settings.language,
            demucs_available=self._demucs_available,
        )
        content.addLayout(lang_music_row)
        layout.addWidget(card)

    def _add_actions_card(self, layout: QVBoxLayout) -> None:
        """Aggiunge la card delle azioni con griglia 2x2."""
        card = Card("AZIONI", self)
        content = card.content_layout()
        grid, self._transcribe_btn, self._clear_btn, self._save_btn, self._stop_btn = (
            build_actions_grid()
        )
        content.addLayout(grid)
        layout.addWidget(card)
        self._transcribe_btn.action_requested.connect(self._on_transcribe)
        self._stop_btn.action_requested.connect(self._on_stop)
        self._clear_btn.action_requested.connect(self._on_clear)
        self._save_btn.action_requested.connect(self._on_save)

    def _add_text_area(self, layout: QVBoxLayout) -> None:
        """Aggiunge l'area di testo della trascrizione."""
        self._text_area = QTextEdit()
        self._text_area.setObjectName("fileTranscriptionArea")
        self._text_area.setReadOnly(True)
        self._text_area.setPlaceholderText(
            "Seleziona un file audio e clicca 'Trascrivi'...\n\n"
            "Supporta file .mp3 e .wav.\n"
            "Funziona sia con audio pulito che con canzoni.\n\n"
            "Per le canzoni: attiva 'Musica' per risultati ottimali."
        )
        self._text_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._text_area)

    def _add_status_bar(self, layout: QVBoxLayout) -> None:
        """Aggiunge la barra di stato con indicatore, fase e progressione."""
        row = QWidget()
        row.setObjectName("statusBar")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(8, 2, 8, 2)
        hl.setSpacing(12)
        self._indicator = StatusIndicator()
        hl.addWidget(self._indicator)
        self._status_label = QLabel("Pronto")
        self._status_label.setStyleSheet(STATUS_STYLE)
        hl.addWidget(self._status_label)
        hl.addStretch()
        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet(STATUS_STYLE)
        self._progress_label.setMinimumWidth(90)
        hl.addWidget(self._progress_label)
        self._segment_label = QLabel("")
        self._segment_label.setStyleSheet(STATUS_STYLE)
        hl.addWidget(self._segment_label)
        layout.addWidget(row)

    # -- Azioni utente ---------------------------------------------------

    def _on_browse(self) -> None:
        """Apre la finestra di selezione file audio."""
        path, _ = QFileDialog.getOpenFileName(self, "Seleziona file audio", "", FILE_FILTER)
        if path:
            self._file_path = path
            self._file_label.setText(Path(path).name)
            self._file_label.setToolTip(path)
            self._file_label.setStyleSheet(file_label_style(True))

    def _on_transcribe(self) -> None:
        """Avvia la trascrizione del file selezionato."""
        if not self._file_path:
            QMessageBox.information(self, "Nessun file", "Seleziona un file audio prima di avviare.")
            return
        if not Path(self._file_path).exists():
            QMessageBox.warning(self, "File non trovato", f"Il file non esiste:\n{self._file_path}")
            return
        self._text_area.clear()
        self._full_text = ""
        self._current_percent = 0
        self._progress_label.setText("")
        self._segment_count = 0
        self._current_phase = "idle"
        music_mode = self._music_checkbox.isChecked()
        # In modalita musica: song_mode=True e, se Demucs disponibile, isolamento vocale attivo
        song_mode = music_mode
        isolate = music_mode and self._demucs_available
        self._controller.start_file_transcription(
            file_path=self._file_path,
            language=self._lang_combo.currentData(),
            song_mode=song_mode, isolate_vocals_flag=isolate,
        )
        self._apply_state(running=True)

    def _on_stop(self) -> None:
        """Ferma la trascrizione in corso."""
        self._controller.stop_file_transcription()
        self._apply_state(running=False)

    def _on_clear(self) -> None:
        """Cancella il testo e azzera la progressione."""
        self._text_area.clear()
        self._full_text = ""
        self._current_percent = 0
        self._progress_label.setText("")
        self._segment_label.setText("")

    def _on_save(self) -> None:
        """Salva il testo trascritto su file."""
        if not self._full_text.strip():
            QMessageBox.information(self, "Nessun testo", "Non c'e testo da salvare.")
            return
        default_name = (Path(self._file_path).stem + ".txt") if self._file_path else "trascrizione.txt"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Salva trascrizione", default_name, "File di testo (*.txt)")
        if save_path:
            try:
                Path(save_path).write_text(self._full_text, encoding="utf-8")
            except OSError as exc:
                QMessageBox.warning(self, "Errore salvataggio", f"Impossibile salvare:\n{exc}")

    # -- Slot per EventBridge --------------------------------------------

    @Slot(str)
    def append_text(self, text: str) -> None:
        """Aggiunge un segmento di testo alla trascrizione.

        Args:
            text: Testo del segmento trascritto.
        """
        self._segment_count += 1
        cursor = self._text_area.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text + "\n")
        self._text_area.setTextCursor(cursor)
        self._text_area.ensureCursorVisible()
        self._segment_label.setText(f"Segmenti: {self._segment_count}")

    @Slot(int)
    def update_progress(self, percent: int) -> None:
        """Aggiorna la progressione nella barra di stato.

        Args:
            percent: Percentuale di avanzamento (0-100).
        """
        self._current_percent = min(percent, 100)
        self._progress_label.setText(f"{self._current_percent}/100")

    @Slot(str)
    def update_status(self, status: str) -> None:
        """Aggiorna lo stato della scheda in base alla fase corrente.

        Args:
            status: Nome della fase (es. ``"running"``, ``"completed"``).
        """
        self._current_phase = status
        self._indicator.set_state(status_to_indicator_state(status))
        self._status_label.setText(status_label(status))
        if status == "completed":
            self._current_percent = 100
            self._progress_label.setText("100/100")
            self._apply_state(running=False, completed=True)

    @Slot(str)
    def show_error(self, message: str) -> None:
        """Mostra un messaggio di errore nella barra di stato.

        Args:
            message: Messaggio di errore da mostrare.
        """
        self._status_label.setText(f"Errore: {message}")
        self._status_label.setStyleSheet(error_status_style())

    @Slot()
    def on_completed(self) -> None:
        """Segnala il completamento della trascrizione."""
        self._apply_state(running=False, completed=True)

    # -- Stato interno ---------------------------------------------------

    def _apply_state(self, running: bool = False, completed: bool = False) -> None:
        """Aggiorna lo stato dei controlli. running=True disabilita i campi."""
        self._transcribe_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._browse_btn.setEnabled(not running)
        self._lang_combo.setEnabled(not running)
        self._music_checkbox.setEnabled(not running)
        self._save_btn.setEnabled(not running and bool(self._full_text.strip()))
        if completed:
            self._current_percent = 100
            self._progress_label.setText("100/100")
