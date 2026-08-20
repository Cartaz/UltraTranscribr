# ui/widgets/live_tab.py
"""Scheda Live — trascrizione audio in tempo reale da Firefox o microfono.

Contiene l'interfaccia per la configurazione e il controllo della
trascrizione live, con pannello configurazione, azioni, area di testo
e barra di stato dedicata. Supporta la drain mode: fermare la cattura
audio lasciando il transcriber svuotare il buffer residuo.

Classes:
    LiveTab: Scheda per la trascrizione audio live.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import (
    QMessageBox, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

from config.constants import ProcessDefaults, UIConstraints
from config.settings import AudioSource
from config.theme import ThemeColors
from core.app_controller import AppController
from core.exceptions import SinkNotFoundError
from core.models import StatusEnum
from ui.styles.components import status_label
from ui.widgets.card import Card
from ui.widgets.config_panel import ConfigPanel
from ui.widgets.live_tab_helpers import (
    build_actions_grid,
    build_status_bar,
    buffer_level_style,
    stat_label_style,
    status_to_indicator_state,
)

logger = logging.getLogger(__name__)


class LiveTab(QWidget):
    """Scheda per la trascrizione audio in tempo reale.

    Args:
        controller: Controller principale dell'applicazione.
        parent: Widget genitore.
    """

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Costruisce il layout completo della scheda Live."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._add_config_card(layout)
        self._add_actions_card(layout)
        self._add_transcription_area(layout)
        self._add_status_bar(layout)

    def _add_config_card(self, layout: QVBoxLayout) -> None:
        """Aggiunge la card di configurazione."""
        card = Card("CONFIGURAZIONE LIVE", self)
        content = card.content_layout()
        self._config_panel = ConfigPanel(self._controller.settings, self)
        self._config_panel.refresh_sinks(self._controller.settings)
        self._config_panel.source_changed.connect(self._on_source_changed)
        content.addWidget(self._config_panel)
        layout.addWidget(card)

    def _add_actions_card(self, layout: QVBoxLayout) -> None:
        """Aggiunge la card delle azioni con griglia adattiva."""
        card = Card("AZIONI", self)
        content = card.content_layout()
        (grid, self._start_btn, self._stop_listening_btn,
         self._stop_btn, self._clear_btn, self._refresh_btn) = build_actions_grid()
        content.addLayout(grid)
        layout.addWidget(card)

        self._start_btn.action_requested.connect(self.on_start)
        self._stop_listening_btn.action_requested.connect(self.on_stop_listening)
        self._stop_btn.action_requested.connect(self.on_stop)
        self._clear_btn.action_requested.connect(self._on_clear)
        self._refresh_btn.action_requested.connect(self._refresh_sinks)

    def _add_transcription_area(self, layout: QVBoxLayout) -> None:
        """Aggiunge l'area di testo della trascrizione."""
        self._text_area = QTextEdit()
        self._text_area.setObjectName("transcriptionArea")
        self._text_area.setReadOnly(True)
        self._text_area.setPlaceholderText("La trascrizione apparirà qui...")
        self._text_area.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._text_area)

    def _add_status_bar(self, layout: QVBoxLayout) -> None:
        """Aggiunge la barra di stato con indicatore e statistiche."""
        (row, self._indicator, self._status_label,
         self._buffer_label, self._stats_label) = build_status_bar()
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start(UIConstraints.STATS_UPDATE_INTERVAL_MS)
        layout.addWidget(row)

    # ═══════════════════════════════════════════════════════════════
    # Azioni
    # ═══════════════════════════════════════════════════════════════

    def on_start(self) -> None:
        """Avvia la trascrizione live tramite il controller."""
        audio_source = self._config_panel.audio_source
        keyword = (ProcessDefaults.SINK_SEARCH_KEYWORD_FIREFOX
                   if audio_source == AudioSource.FIREFOX.value
                   else ProcessDefaults.SINK_SEARCH_KEYWORD_MIC)
        self._controller.update_settings(
            language=self._config_panel.language,
            audio_source=audio_source,
            sink_name=self._config_panel.sink_name,
            sink_search_keyword=keyword,
        )
        try:
            self._controller.start_transcription(
                sink_name=self._config_panel.sink_name,
                audio_source=audio_source,
                language=self._config_panel.language,
            )
        except SinkNotFoundError as exc:
            QMessageBox.warning(self, "Dispositivo non trovato", exc.message)

    def on_stop(self) -> None:
        """Ferma la trascrizione live tramite il controller."""
        self._controller.stop_transcription()

    def on_stop_listening(self) -> None:
        """Ferma la cattura audio lasciando il transcriber svuotare il buffer.

        Passa in drain mode: il producer si ferma (nessun nuovo chunk
        nella RAM), il consumer continua a trascrivere i dati residui.
        """
        if not self._controller.is_running():
            logger.warning("Nessuna cattura attiva da fermare")
            return
        self._controller.stop_listening()
        self._stop_listening_btn.setEnabled(False)
        self.update_status("draining")

    def _on_clear(self) -> None:
        """Cancella il testo della trascrizione."""
        self._text_area.clear()
        self._controller.buffer.clear()

    def _on_source_changed(self) -> None:
        """Aggiorna la lista dispositivi quando cambia la fonte audio."""
        self._refresh_sinks()
        self._text_area.setPlaceholderText("La trascrizione apparirà qui...")

    def _refresh_sinks(self) -> None:
        """Aggiorna il dropdown dei dispositivi."""
        self._config_panel.refresh_sinks(self._controller.settings)

    # ═══════════════════════════════════════════════════════════════
    # Slot per EventBridge
    # ═══════════════════════════════════════════════════════════════

    @Slot(str)
    def append_text(self, text: str) -> None:
        """Aggiunge testo all'area di trascrizione."""
        cursor = self._text_area.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text + "\n")
        self._text_area.setTextCursor(cursor)
        self._text_area.ensureCursorVisible()

    @Slot()
    def enable_running_state(self) -> None:
        """Abilita lo stato UI di esecuzione."""
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._stop_listening_btn.setEnabled(True)
        self._config_panel.set_enabled(False)
        self._refresh_btn.setEnabled(False)

    @Slot()
    def enable_idle_state(self) -> None:
        """Abilita lo stato UI di riposo."""
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._stop_listening_btn.setEnabled(False)
        self._config_panel.set_enabled(True)
        self._refresh_btn.setEnabled(True)
        self.update_status(StatusEnum.STOPPED.value)

    @Slot()
    def on_drain_completed(self) -> None:
        """Gestisce il completamento del drain del buffer.

        Chiamato quando il TranscriberThread ha svuotato completamente
        il buffer residuo dopo che la cattura audio e stata fermata.
        Ripristina la UI allo stato idle.
        """
        logger.info("Drain completato — ripristino stato idle")
        self._controller.stop_transcription()
        self.enable_idle_state()
        self.update_status(StatusEnum.COMPLETED.value)

    @Slot(str)
    def update_status(self, status: str) -> None:
        """Aggiorna l'indicatore e l'etichetta di stato."""
        self._indicator.set_state(status_to_indicator_state(status))
        self._status_label.setText(status_label(status))
        self._status_label.setStyleSheet(stat_label_style())

    @Slot(int)
    def update_buffer_level(self, level: int) -> None:
        """Aggiorna l'etichetta del livello buffer."""
        _, style = buffer_level_style(level)
        self._buffer_label.setText(f"{level}%")
        self._buffer_label.setStyleSheet(style)

    @Slot(str)
    def show_error(self, message: str) -> None:
        """Mostra un errore nella barra di stato."""
        self._status_label.setText(f"Errore: {message}")
        self._status_label.setStyleSheet(
            f"color: {ThemeColors.STATUS_ERROR};")

    def _update_stats(self) -> None:
        """Aggiorna periodicamente le statistiche del buffer."""
        buf = self._controller.buffer
        put_t = buf.total_put
        get_t = buf.total_get
        depth = buf.qsize
        # Mostra 0.0% quando ci sono put ma nessun get ancora; mostra "-"
        # solo quando non ci sono ancora put (statistica non calcolabile).
        if put_t > 0:
            ratio = f"{get_t / put_t:.1%}"
        else:
            ratio = "-"
        self._stats_label.setText(
            f"In: {put_t}  Out: {get_t}  Coda: {depth}  Recupero: {ratio}")

    def stop_timer(self) -> None:
        """Ferma il timer delle statistiche."""
        self._stats_timer.stop()
