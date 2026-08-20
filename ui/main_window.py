"""Main Qt window."""
from __future__ import annotations
from PySide6.QtGui import QCloseEvent,QKeySequence,QShortcut
from PySide6.QtWidgets import QLabel,QMainWindow,QTabWidget,QVBoxLayout,QWidget,QApplication
from core.app_controller import AppController
from ui.event_bridge import EventBridge
from ui.styles import build_stylesheet
from ui.tray_icon import TrayIcon
from ui.widgets.file_tab import FileTab
from ui.widgets.live_tab import LiveTab

class MainWindow(QMainWindow):
    def __init__(self,controller:AppController):
        super().__init__(); self._controller=controller; self._tray_icon=None; self._setup_ui(); self._connect_bridge()
        self.setStyleSheet(build_stylesheet()); self.setWindowTitle("UltraTranscribr")
        self.resize(controller.settings.window_width,controller.settings.window_height)
        self._quit_shortcut=QShortcut(QKeySequence("Ctrl+Q"),self); self._quit_shortcut.setAutoRepeat(False); self._quit_shortcut.activated.connect(self.force_quit)
        self._minimize_shortcut=QShortcut(QKeySequence("Ctrl+M"),self); self._minimize_shortcut.setAutoRepeat(False); self._minimize_shortcut.activated.connect(self._minimize_to_tray)
    def _setup_ui(self):
        central=QWidget(); central.setObjectName("centralContainer"); self.setCentralWidget(central)
        root=QVBoxLayout(central); root.setContentsMargins(16,12,16,8); root.setSpacing(8)
        title=QLabel("UltraTranscribr"); title.setObjectName("titleLabel"); root.addWidget(title)
        subtitle=QLabel("Trascrizione audio: live da Firefox/microfono o da file"); subtitle.setObjectName("subtitleLabel"); root.addWidget(subtitle)
        self._tab_widget=QTabWidget(); self._tab_widget.setObjectName("mainTabs")
        self._live_tab=LiveTab(self._controller,self); self._file_tab=FileTab(self._controller,self)
        self._tab_widget.addTab(self._live_tab,"Live"); self._tab_widget.addTab(self._file_tab,"File"); root.addWidget(self._tab_widget)
    def _connect_bridge(self):
        self._bridge=EventBridge()
        self._bridge.live_new_text.connect(self._live_tab.append_text); self._bridge.live_status_changed.connect(self._live_tab.update_status)
        self._bridge.live_buffer_level.connect(self._live_tab.update_buffer_level); self._bridge.live_error.connect(self._live_tab.show_error)
        self._bridge.process_started.connect(self._live_tab.enable_running_state); self._bridge.process_stopped.connect(self._live_tab.enable_idle_state)
        self._bridge.drain_completed.connect(self._live_tab.on_drain_completed)
        self._bridge.file_new_text.connect(self._file_tab.append_text); self._bridge.file_status_changed.connect(self._file_tab.update_status)
        self._bridge.file_progress.connect(self._file_tab.update_progress); self._bridge.file_error.connect(self._file_tab.show_error)
        self._bridge.file_completed.connect(self._file_tab.on_completed); self._bridge.file_full_text.connect(self._on_file_full_text)
    def _on_file_full_text(self,text): self._file_tab._full_text=text
    def on_start(self): self._live_tab.on_start()
    def on_stop(self): self._live_tab.on_stop()
    def _shutdown(self):
        self._live_tab.stop_timer(); self._controller.shutdown()
    def closeEvent(self,event:QCloseEvent): self._shutdown(); event.accept()
    def set_tray_icon(self,tray_icon:TrayIcon): self._tray_icon=tray_icon
    def force_quit(self): self._shutdown(); QApplication.instance().quit()
    def _minimize_to_tray(self): self.hide()
