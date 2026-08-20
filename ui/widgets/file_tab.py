"""File transcription tab."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Slot
from PySide6.QtWidgets import QFileDialog,QMessageBox,QTextEdit,QSizePolicy,QVBoxLayout,QWidget,QLabel,QHBoxLayout
from core.app_controller import AppController
from core.vocal_isolator import is_demucs_available
from ui.styles.components import status_label
from ui.widgets.card import Card
from ui.widgets.file_tab_helpers import (
    FILE_FILTER,STATUS_STYLE,build_actions_grid,build_file_row,build_lang_music_row,
    error_status_style,file_label_style,status_to_indicator_state,
)
from ui.widgets.status_indicator import StatusIndicator

class FileTab(QWidget):
    def __init__(self,controller:AppController,parent=None):
        super().__init__(parent); self._controller=controller; self._file_path=None
        self._full_text=""; self._segment_count=0; self._demucs_available=is_demucs_available()
        self._current_phase="idle"; self._current_percent=0; self._setup_ui()
    def _setup_ui(self):
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.setSpacing(8)
        card=Card("CONFIGURAZIONE FILE",self); content=card.content_layout()
        row,self._file_label,self._browse_btn=build_file_row(); self._browse_btn.action_requested.connect(self._on_browse); content.addLayout(row)
        row,self._lang_combo,self._music_checkbox=build_lang_music_row(
            initial_lang=self._controller.settings.language,demucs_available=self._demucs_available)
        content.addLayout(row); layout.addWidget(card)
        card=Card("AZIONI",self); content=card.content_layout()
        grid,self._transcribe_btn,self._clear_btn,self._save_btn,self._stop_btn=build_actions_grid()
        content.addLayout(grid); layout.addWidget(card)
        self._transcribe_btn.action_requested.connect(self._on_transcribe)
        self._stop_btn.action_requested.connect(self._on_stop)
        self._clear_btn.action_requested.connect(self._on_clear)
        self._save_btn.action_requested.connect(self._on_save)
        self._text_area=QTextEdit(); self._text_area.setObjectName("fileTranscriptionArea"); self._text_area.setReadOnly(True)
        self._text_area.setPlaceholderText("Seleziona un file audio e clicca 'Trascrivi'...")
        self._text_area.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding); layout.addWidget(self._text_area)
        row=QWidget(); row.setObjectName("statusBar"); hl=QHBoxLayout(row); hl.setContentsMargins(8,2,8,2); hl.setSpacing(12)
        self._indicator=StatusIndicator(); hl.addWidget(self._indicator)
        self._status_label=QLabel("Pronto"); self._status_label.setStyleSheet(STATUS_STYLE); hl.addWidget(self._status_label); hl.addStretch()
        self._progress_label=QLabel(""); self._progress_label.setStyleSheet(STATUS_STYLE); self._progress_label.setMinimumWidth(90); hl.addWidget(self._progress_label)
        self._segment_label=QLabel(""); self._segment_label.setStyleSheet(STATUS_STYLE); hl.addWidget(self._segment_label); layout.addWidget(row)
    def _on_browse(self):
        path,_=QFileDialog.getOpenFileName(self,"Seleziona file audio","",FILE_FILTER)
        if path:
            self._file_path=path; self._file_label.setText(Path(path).name); self._file_label.setToolTip(path)
            self._file_label.setStyleSheet(file_label_style(True))
    def _on_transcribe(self):
        if not self._file_path:
            QMessageBox.information(self,"Nessun file","Seleziona un file audio prima di avviare."); return
        if not Path(self._file_path).exists():
            QMessageBox.warning(self,"File non trovato",f"Il file non esiste:\n{self._file_path}"); return
        self._text_area.clear(); self._full_text=""; self._segment_count=0; self._current_percent=0
        self._progress_label.clear(); self._segment_label.clear(); self._status_label.setStyleSheet(STATUS_STYLE)
        music=self._music_checkbox.isChecked(); self._apply_state(running=True)
        try:
            self._controller.start_file_transcription(
                self._file_path,language=self._lang_combo.currentData(),
                song_mode=music,isolate_vocals_flag=music and self._demucs_available)
        except Exception as exc:
            self.show_error(str(exc))
    def _on_stop(self):
        self._controller.stop_file_transcription(); self._apply_state(False)
    def _on_clear(self):
        self._text_area.clear(); self._full_text=""; self._segment_count=0
        self._progress_label.clear(); self._segment_label.clear(); self._save_btn.setEnabled(False)
    def _on_save(self):
        if not self._full_text.strip(): return
        default=(Path(self._file_path).stem+".txt") if self._file_path else "trascrizione.txt"
        path,_=QFileDialog.getSaveFileName(self,"Salva trascrizione",default,"File di testo (*.txt)")
        if path:
            try: Path(path).write_text(self._full_text,encoding="utf-8")
            except OSError as exc: QMessageBox.warning(self,"Errore salvataggio",str(exc))
    @Slot(str)
    def append_text(self,text):
        if not text: return
        self._segment_count+=1; cur=self._text_area.textCursor(); cur.movePosition(cur.MoveOperation.End)
        cur.insertText(text+"\n"); self._text_area.setTextCursor(cur); self._text_area.ensureCursorVisible()
        self._segment_label.setText(f"Segmenti: {self._segment_count}")
    @Slot(int)
    def update_progress(self,percent):
        self._current_percent=max(0,min(int(percent),100)); self._progress_label.setText(f"{self._current_percent}/100")
    @Slot(str)
    def update_status(self,status):
        self._current_phase=status; self._indicator.set_state(status_to_indicator_state(status))
        self._status_label.setText(status_label(status)); self._status_label.setStyleSheet(STATUS_STYLE)
        if status=="completed": self.update_progress(100); self._apply_state(False,True)
        elif status in ("error","stopped"): self._apply_state(False)
    @Slot(str)
    def show_error(self,message):
        self._current_phase="error"; self._status_label.setText(f"Errore: {message}")
        self._status_label.setStyleSheet(error_status_style()); self._apply_state(False)
    @Slot()
    def on_completed(self): self._apply_state(False,True)
    def _apply_state(self,running=False,completed=False):
        self._transcribe_btn.setEnabled(not running); self._stop_btn.setEnabled(running)
        self._browse_btn.setEnabled(not running); self._lang_combo.setEnabled(not running)
        self._music_checkbox.setEnabled(not running)
        self._save_btn.setEnabled(not running and bool(self._full_text.strip()))
        if completed: self.update_progress(100)
