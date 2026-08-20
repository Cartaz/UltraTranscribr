"""Live transcription tab."""
from __future__ import annotations
import logging
from PySide6.QtCore import QTimer,Slot
from PySide6.QtWidgets import QMessageBox,QSizePolicy,QTextEdit,QVBoxLayout,QWidget
from config.constants import ProcessDefaults,UIConstraints
from config.settings import AudioSource
from config.theme import ThemeColors
from core.app_controller import AppController
from core.exceptions import SinkNotFoundError
from core.models import StatusEnum
from ui.styles.components import status_label
from ui.widgets.card import Card
from ui.widgets.config_panel import ConfigPanel
from ui.widgets.live_tab_helpers import build_actions_grid,build_status_bar,buffer_level_style,stat_label_style,status_to_indicator_state
logger=logging.getLogger(__name__)

class LiveTab(QWidget):
    def __init__(self,controller:AppController,parent=None):
        super().__init__(parent); self._controller=controller; self._setup_ui()
    def _setup_ui(self):
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.setSpacing(8)
        card=Card("CONFIGURAZIONE LIVE",self); content=card.content_layout()
        self._config_panel=ConfigPanel(self._controller.settings,self); self._config_panel.refresh_sinks(self._controller.settings)
        self._config_panel.source_changed.connect(self._refresh_sinks); content.addWidget(self._config_panel); layout.addWidget(card)
        card=Card("AZIONI",self); content=card.content_layout()
        grid,self._start_btn,self._stop_listening_btn,self._stop_btn,self._clear_btn,self._refresh_btn=build_actions_grid()
        content.addLayout(grid); layout.addWidget(card)
        self._start_btn.action_requested.connect(self.on_start); self._stop_listening_btn.action_requested.connect(self.on_stop_listening)
        self._stop_btn.action_requested.connect(self.on_stop); self._clear_btn.action_requested.connect(self._on_clear)
        self._refresh_btn.action_requested.connect(self._refresh_sinks)
        self._text_area=QTextEdit(); self._text_area.setObjectName("transcriptionArea"); self._text_area.setReadOnly(True)
        self._text_area.setPlaceholderText("La trascrizione apparirà qui...")
        self._text_area.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding); layout.addWidget(self._text_area)
        row,self._indicator,self._status_label,self._buffer_label,self._stats_label=build_status_bar()
        self._stats_timer=QTimer(self); self._stats_timer.timeout.connect(self._update_stats); self._stats_timer.start(UIConstraints.STATS_UPDATE_INTERVAL_MS)
        layout.addWidget(row)
    def on_start(self):
        src=self._config_panel.audio_source
        keyword=ProcessDefaults.SINK_SEARCH_KEYWORD_FIREFOX if src==AudioSource.FIREFOX.value else ProcessDefaults.SINK_SEARCH_KEYWORD_MIC
        self._controller.update_settings(language=self._config_panel.language,audio_source=src,
            sink_name=self._config_panel.sink_name,sink_search_keyword=keyword)
        try: self._controller.start_transcription(self._config_panel.sink_name,src,self._config_panel.language)
        except SinkNotFoundError as exc: QMessageBox.warning(self,"Dispositivo non trovato",exc.message)
        except Exception as exc: self.show_error(str(exc))
    def on_stop(self): self._controller.stop_transcription()
    def on_stop_listening(self):
        if not self._controller.is_running(): return
        self._controller.stop_listening(); self._stop_listening_btn.setEnabled(False); self.update_status("draining")
    def _on_clear(self):
        self._text_area.clear()
    def _refresh_sinks(self): self._config_panel.refresh_sinks(self._controller.settings)
    @Slot(str)
    def append_text(self,text):
        cur=self._text_area.textCursor(); cur.movePosition(cur.MoveOperation.End); cur.insertText(text+"\n")
        self._text_area.setTextCursor(cur); self._text_area.ensureCursorVisible()
    @Slot()
    def enable_running_state(self):
        self._start_btn.setEnabled(False); self._stop_btn.setEnabled(True); self._stop_listening_btn.setEnabled(True)
        self._config_panel.set_enabled(False); self._refresh_btn.setEnabled(False)
    @Slot()
    def enable_idle_state(self):
        self._start_btn.setEnabled(True); self._stop_btn.setEnabled(False); self._stop_listening_btn.setEnabled(False)
        self._config_panel.set_enabled(True); self._refresh_btn.setEnabled(True)
    @Slot()
    def on_drain_completed(self):
        self._controller.stop_transcription(); self.enable_idle_state(); self.update_status(StatusEnum.COMPLETED.value)
    @Slot(str)
    def update_status(self,status):
        self._indicator.set_state(status_to_indicator_state(status)); self._status_label.setText(status_label(status))
        self._status_label.setStyleSheet(stat_label_style())
    @Slot(int)
    def update_buffer_level(self,level):
        _,style=buffer_level_style(level); self._buffer_label.setText(f"{level}%"); self._buffer_label.setStyleSheet(style)
    @Slot(str)
    def show_error(self,message):
        self._status_label.setText(f"Errore: {message}"); self._status_label.setStyleSheet(f"color:{ThemeColors.STATUS_ERROR};")
        self.enable_idle_state()
    def _update_stats(self):
        b=self._controller.buffer; put_t,get_t=b.total_put,b.total_get
        ratio=f"{get_t/put_t:.1%}" if put_t else "-"
        self._stats_label.setText(f"In: {put_t}  Out: {get_t}  Coda: {b.qsize}  Recupero: {ratio}")
    def stop_timer(self): self._stats_timer.stop()
