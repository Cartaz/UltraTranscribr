# ui/main_window.py
"""Finestra principale di UltraTranscribr con schede Live e File.

Hub UI centrale con QTabWidget che ospita la scheda Live per la
trascrizione in tempo reale e la scheda File per la trascrizione
di file audio. Comunica con core tramite AppController ed EventBridge.

Classes:
    MainWindow: Finestra principale dell'applicazione.
"""

from __future__ import annotations

import logging

from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget,
)

from config.constants import UIConstraints
from core.app_controller import AppController
from core.models import StatusEnum
from ui.event_bridge import EventBridge
from ui.styles import build_stylesheet
from ui.tray_icon import TrayIcon
from ui.widgets.file_tab import FileTab
from ui.widgets.live_tab import LiveTab

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Finestra principale dell'applicazione UltraTranscribr.

    Utilizza un QTabWidget con due schede:
      - Live: trascrizione audio in tempo reale
      - File: trascrizione di file audio (.mp3, .wav)

    Args:
        controller: Controller principale dell'applicazione.
    """

    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self._controller = controller
        self._tray_icon: TrayIcon | None = None

        self._setup_ui()
        self._connect_bridge()
        self.setStyleSheet(build_stylesheet())
        self.setWindowTitle("UltraTranscribr")
        self.resize(controller.settings.window_width,
                     controller.settings.window_height)

        # ── Scorciatoie da tastiera ─────────────────────────────────
        self._quit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        self._quit_shortcut.activated.connect(self.force_quit)
        self._minimize_shortcut = QShortcut(QKeySequence("Ctrl+M"), self)
        self._minimize_shortcut.activated.connect(self._minimize_to_tray)

    # ═══════════════════════════════════════════════════════════════
    # Costruzione UI
    # ═══════════════════════════════════════════════════════════════

    def _setup_ui(self) -> None:
        """Costruisce il layout completo dell'interfaccia."""
        central = QWidget()
        central.setObjectName("centralContainer")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 8)
        root.setSpacing(8)

        self._add_title(root)
        self._add_tabs(root)

    def _add_title(self, layout: QVBoxLayout) -> None:
        """Aggiunge titolo e sottotitolo."""
        title = QLabel("UltraTranscribr")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        subtitle = QLabel(
            "Trascrizione audio: live da Firefox/microfono o da file")
        subtitle.setObjectName("subtitleLabel")
        layout.addWidget(subtitle)

    def _add_tabs(self, layout: QVBoxLayout) -> None:
        """Aggiunge il widget a schede con Live e File."""
        self._tab_widget = QTabWidget()
        self._tab_widget.setObjectName("mainTabs")

        self._live_tab = LiveTab(self._controller, self)
        self._file_tab = FileTab(self._controller, self)

        self._tab_widget.addTab(self._live_tab, "Live")
        self._tab_widget.addTab(self._file_tab, "File")

        layout.addWidget(self._tab_widget)

    # ═══════════════════════════════════════════════════════════════
    # EventBridge — Thread-safe UI updates
    # ═══════════════════════════════════════════════════════════════

    def _connect_bridge(self) -> None:
        """Collega l'EventBridge ai componenti UI di ciascuna scheda."""
        self._bridge = EventBridge()

        # ── Segnali Live ──────────────────────────────────────────
        self._bridge.live_new_text.connect(self._live_tab.append_text)
        self._bridge.live_status_changed.connect(self._live_tab.update_status)
        self._bridge.live_buffer_level.connect(self._live_tab.update_buffer_level)
        self._bridge.live_error.connect(self._live_tab.show_error)
        self._bridge.process_started.connect(self._live_tab.enable_running_state)
        self._bridge.process_stopped.connect(self._live_tab.enable_idle_state)
        self._bridge.drain_completed.connect(self._live_tab.on_drain_completed)

        # ── Segnali File ──────────────────────────────────────────
        self._bridge.file_new_text.connect(self._file_tab.append_text)
        self._bridge.file_status_changed.connect(self._file_tab.update_status)
        self._bridge.file_progress.connect(self._file_tab.update_progress)
        self._bridge.file_error.connect(self._file_tab.show_error)
        self._bridge.file_completed.connect(self._file_tab.on_completed)
        self._bridge.file_full_text.connect(self._on_file_full_text)

    def _on_file_full_text(self, text: str) -> None:
        """Riceve il testo completo dalla trascrizione file.

        Args:
            text: Testo completo della trascrizione.
        """
        self._file_tab._full_text = text

    # ═══════════════════════════════════════════════════════════════
    # API Pubblica (per TrayIcon e main.py)
    # ═══════════════════════════════════════════════════════════════

    def on_start(self) -> None:
        """Avvia la trascrizione live (chiamato dal tray)."""
        self._live_tab.on_start()

    def on_stop(self) -> None:
        """Ferma la trascrizione live (chiamato dal tray)."""
        self._live_tab.on_stop()

    # ═══════════════════════════════════════════════════════════════
    # Eventi finestra
    # ═══════════════════════════════════════════════════════════════

    def closeEvent(self, event: QCloseEvent) -> None:
        """Chiude l'applicazione quando l'utente preme X.

        Args:
            event: Evento di chiusura della finestra.
        """
        self._controller.stop_transcription()
        self._controller.stop_file_transcription()
        self._live_tab.stop_timer()
        event.accept()

    def set_tray_icon(self, tray_icon: TrayIcon) -> None:
        """Imposta il riferimento al tray icon.

        Args:
            tray_icon: Istanza di TrayIcon.
        """
        self._tray_icon = tray_icon

    def force_quit(self) -> None:
        """Ferma i thread e chiude l'applicazione."""
        self._controller.stop_transcription()
        self._controller.stop_file_transcription()
        self._live_tab.stop_timer()
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()

    def _minimize_to_tray(self) -> None:
        """Riduce la finestra a icona volante nel tray."""
        self.hide()
