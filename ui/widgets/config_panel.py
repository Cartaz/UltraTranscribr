# ui/widgets/config_panel.py
"""Pannello configurazione: stessa geometria, controlli neumorfici custom."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from config.settings import AudioSource, Settings
from core.sink_finder import (
    find_firefox_sink,
    find_microphone,
    list_available_devices,
)
from ui.widgets.neumorphic import NeumorphicComboBox

_LANGUAGE_MAP = {
    "en": "Inglese",
    "it": "Italiano",
}

_SOURCE_MAP = {
    AudioSource.FIREFOX.value: "Firefox",
    AudioSource.MICROPHONE.value: "Microfono",
}


class ConfigPanel(QWidget):
    source_changed = Signal()

    def __init__(
        self,
        settings: Settings,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(8)

        row1.addWidget(QLabel("Lingua:"))
        self._language_combo = NeumorphicComboBox()
        for code, label in _LANGUAGE_MAP.items():
            self._language_combo.addItem(label, code)
        lang_idx = self._language_combo.findData(
            self._settings.language
        )
        if lang_idx >= 0:
            self._language_combo.setCurrentIndex(lang_idx)
        self._language_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        row1.addWidget(self._language_combo)

        row1.addWidget(QLabel("Fonte:"))
        self._source_combo = NeumorphicComboBox()
        for value, label in _SOURCE_MAP.items():
            self._source_combo.addItem(label, value)
        src_idx = self._source_combo.findData(
            self._settings.audio_source
        )
        if src_idx >= 0:
            self._source_combo.setCurrentIndex(src_idx)
        self._source_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._source_combo.currentIndexChanged.connect(
            self._on_source_changed
        )
        row1.addWidget(self._source_combo)
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(QLabel("Dispositivo:"))
        self._sink_combo = NeumorphicComboBox()
        self._sink_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        row2.addWidget(self._sink_combo)
        outer.addLayout(row2)

    @property
    def language(self) -> str:
        return self._language_combo.currentData() or "en"

    @property
    def audio_source(self) -> str:
        return (
            self._source_combo.currentData()
            or AudioSource.FIREFOX.value
        )

    @property
    def sink_name(self) -> Optional[str]:
        data = self._sink_combo.currentData()
        if data == "__auto__":
            return None
        return data

    def refresh_sinks(self, settings: Settings) -> None:
        self._sink_combo.clear()
        source = self.audio_source

        if source == AudioSource.FIREFOX.value:
            self._sink_combo.addItem(
                "Auto-detect (Firefox)", "__auto__"
            )
            detected = find_firefox_sink(settings)
            if detected:
                self._sink_combo.addItem(
                    f"{detected} [Firefox]", detected
                )
            for d in list_available_devices():
                if not d.get("is_monitor", False):
                    continue
                name = d.get("name", "")
                if (
                    not name
                    or self._sink_combo.findData(name) >= 0
                ):
                    continue
                display = (
                    name if len(name) <= 50
                    else name[:47] + "..."
                )
                self._sink_combo.addItem(
                    f"[Monitor] {display}  "
                    f"({d.get('channels', 0)}ch)",
                    name,
                )
        else:
            self._sink_combo.addItem(
                "Auto-detect (Microfono)", "__auto__"
            )
            detected = find_microphone(settings)
            if detected:
                self._sink_combo.addItem(
                    f"{detected} [Mic]", detected
                )
            for d in list_available_devices():
                if not d.get("is_mic", True):
                    continue
                name = d.get("name", "")
                if (
                    not name
                    or self._sink_combo.findData(name) >= 0
                ):
                    continue
                display = (
                    name if len(name) <= 50
                    else name[:47] + "..."
                )
                self._sink_combo.addItem(
                    f"[Mic] {display}  "
                    f"({d.get('channels', 0)}ch)",
                    name,
                )

    def set_enabled(self, enabled: bool) -> None:
        self._language_combo.setEnabled(enabled)
        self._source_combo.setEnabled(enabled)
        self._sink_combo.setEnabled(enabled)

    def _on_source_changed(self) -> None:
        self.source_changed.emit()
