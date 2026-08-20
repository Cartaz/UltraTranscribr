# ui/widgets/action_button.py
"""Action button with status indicator and synchronized shortcut state."""
from __future__ import annotations
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont,QFontMetrics,QKeySequence,QShortcut
from PySide6.QtWidgets import QHBoxLayout,QWidget
from config.theme import ThemeColors
from ui.widgets.neumorphic import NeumorphicButton
from ui.widgets.shortcut_badge import ShortcutBadge
from ui.widgets.status_indicator import StatusIndicator
_BUTTON_REF_TEXT="Debug Audio"; _HPAD=10

def _ref_button_width():
    fm=QFontMetrics(QFont(ThemeColors.FONT_FAMILY,ThemeColors.FONT_SIZE))
    return fm.horizontalAdvance(_BUTTON_REF_TEXT)+2*_HPAD+4

class ActionButton(QWidget):
    action_requested=Signal()
    def __init__(self,label,shortcut="",button_id="",is_danger=False,
                 style_variant="neutral",show_indicator=True,parent=None):
        super().__init__(parent); self._shortcut=None
        layout=QHBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.setSpacing(6)
        self._indicator=StatusIndicator(self) if show_indicator else None
        if self._indicator: layout.addWidget(self._indicator)
        self._button=NeumorphicButton(label,self,danger=is_danger,
            variant="danger" if is_danger else style_variant)
        if button_id: self._button.setObjectName(button_id)
        self._button.setMinimumWidth(_ref_button_width())
        self._button.setStyleSheet(
            f"QPushButton{{background:transparent;color:transparent;border:none;"
            f"padding:6px {_HPAD}px;min-height:26px;font-weight:600;}}")
        self._button.clicked.connect(self.action_requested.emit); layout.addWidget(self._button)
        self._badge=ShortcutBadge(shortcut,self) if shortcut else None
        if self._badge: layout.addWidget(self._badge)
        if shortcut:
            self._shortcut=QShortcut(QKeySequence(shortcut),self)
            self._shortcut.setAutoRepeat(False)
            self._shortcut.activated.connect(self.action_requested.emit)
    def set_status(self,state):
        if self._indicator: self._indicator.set_state(state)
    def setEnabled(self,enabled):
        super().setEnabled(enabled)
        self._button.setEnabled(enabled)
        if self._shortcut is not None: self._shortcut.setEnabled(enabled)
