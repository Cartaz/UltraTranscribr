# ui/widgets/action_button.py
"""Pulsante d'azione con badge scorciatoia e indicatore di stato."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont, QFontMetrics, QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QWidget

from config.theme import ThemeColors
from ui.widgets.neumorphic import NeumorphicButton
from ui.widgets.shortcut_badge import ShortcutBadge
from ui.widgets.status_indicator import StatusIndicator

_BUTTON_REF_TEXT = "Debug Audio"
_HPAD = 10


def _ref_button_width() -> int:
    fm = QFontMetrics(
        QFont(ThemeColors.FONT_FAMILY, ThemeColors.FONT_SIZE)
    )
    return fm.horizontalAdvance(_BUTTON_REF_TEXT) + 2 * _HPAD + 4


class ActionButton(QWidget):
    action_requested = Signal()

    def __init__(
        self,
        label: str,
        shortcut: str = "",
        button_id: str = "",
        is_danger: bool = False,
        style_variant: str = "neutral",
        show_indicator: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._is_danger = is_danger
        self._style_variant = (
            "danger" if is_danger else style_variant
        )
        self._show_indicator = show_indicator
        self._setup_ui(label, shortcut, button_id)

    def _setup_ui(
        self, label: str, shortcut: str, button_id: str
    ) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        if self._show_indicator:
            self._indicator = StatusIndicator(self)
            layout.addWidget(self._indicator)
        else:
            self._indicator = None

        self._button = NeumorphicButton(
            label,
            self,
            danger=self._is_danger,
            variant=self._style_variant,
        )
        if button_id:
            self._button.setObjectName(button_id)

        # Mantiene la stessa metrica della UI originale.
        self._button.setMinimumWidth(_ref_button_width())
        self._button.setStyleSheet(
            f"QPushButton {{"
            f"background: transparent;"
            f"color: transparent;"
            f"border: none;"
            f"padding: 6px {_HPAD}px;"
            f"min-height: 26px;"
            f"font-weight: 600;"
            f"}}"
        )
        self._button.clicked.connect(self.action_requested.emit)
        layout.addWidget(self._button)

        if shortcut:
            self._badge = ShortcutBadge(shortcut, self)
            layout.addWidget(self._badge)
            self._shortcut = QShortcut(QKeySequence(shortcut), self)
            self._shortcut.activated.connect(
                self.action_requested.emit
            )
        else:
            self._badge = None

    def set_status(self, state: StatusIndicator.State) -> None:
        if self._indicator is not None:
            self._indicator.set_state(state)

    def setEnabled(self, enabled: bool) -> None:
        self._button.setEnabled(enabled)
