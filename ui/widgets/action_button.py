# ui/widgets/action_button.py
"""Pulsante d'azione con badge scorciatoia e indicatore di stato.

Combina un QPushButton, un ShortcutBadge e (opzionalmente) uno
StatusIndicator in un'unica unità visiva in stile Neumorphic Dark
con accento RGB(255, 102, 0).
La scorciatoia è registrata nel sistema globale tramite QShortcut.

La larghezza minima dei pulsanti è calcolata rispetto al testo più lungo
("Debug Audio") con 10 px di padding orizzontale per lato. Analogamente,
la larghezza minima dei badge è calcolata su "Ctrl+D" + 10 px per lato.

Classes:
    ActionButton: Pulsante d'azione con scorciatoia e indicatore.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont, QFontMetrics, QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from config.theme import ThemeColors
from ui.widgets.shortcut_badge import ShortcutBadge
from ui.widgets.status_indicator import StatusIndicator

# Testo di riferimento per il calcolo della larghezza minima pulsante
_BUTTON_REF_TEXT = "Debug Audio"
_HPAD = 10  # padding orizzontale per lato (px)


def _ref_button_width() -> int:
    """Calcola la larghezza minima del pulsante in base al testo di riferimento."""
    fm = QFontMetrics(QFont(ThemeColors.FONT_FAMILY, ThemeColors.FONT_SIZE))
    return fm.horizontalAdvance(_BUTTON_REF_TEXT) + 2 * _HPAD + 4  # +4 border


class ActionButton(QWidget):
    """Pulsante d'azione con badge scorciatoia e indicatore di stato.

    Il badge scorciatoia registra la combinazione di tasti nel sistema
    globale. L'indicatore di stato mostra visivamente lo stato del
    processo associato al pulsante.

    Args:
        label: Testo del pulsante.
        shortcut: Scorciatoia tastiera (es. "Ctrl+R"). Vuoto = nessun badge.
        button_id: Identificativo QSS del pulsante (es. "startButton").
        is_danger: Se True, usa i colori DANGER.
        style_variant: Variante visiva: "orange_glow", "orange_text", "neutral", "danger".
        show_indicator: Se True, mostra il socket circolare a sinistra.
        parent: Widget genitore.

    Signals:
        action_requested: Emesso quando l'utente clicca il pulsante
            o preme la scorciatoia.
    """

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
        self._style_variant = "danger" if is_danger else style_variant
        self._show_indicator = show_indicator
        self._setup_ui(label, shortcut, button_id)

    def _setup_ui(self, label: str, shortcut: str, button_id: str) -> None:
        """Configura il layout del widget con pulsante, indicatore e badge.

        Args:
            label: Testo del pulsante.
            shortcut: Scorciatoia tastiera.
            button_id: Identificativo QSS.
        """
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        if self._show_indicator:
            self._indicator = StatusIndicator(self)
            layout.addWidget(self._indicator)
        else:
            self._indicator = None

        self._button = QPushButton(label, self)
        if button_id:
            self._button.setObjectName(button_id)
        # Larghezza minima calcolata su "Debug Audio" + 10px per lato
        self._button.setMinimumWidth(_ref_button_width())
        self._apply_button_style()
        self._button.clicked.connect(self.action_requested.emit)
        layout.addWidget(self._button)

        if shortcut:
            self._badge = ShortcutBadge(shortcut, self)
            layout.addWidget(self._badge)
            self._shortcut = QShortcut(QKeySequence(shortcut), self)
            self._shortcut.activated.connect(self.action_requested.emit)
        else:
            self._badge = None

    def _apply_button_style(self) -> None:
        """Applica lo stile neumorfico al pulsante in base alla variante."""
        bg = ThemeColors.BG_CARD
        border_top = ThemeColors.BORDER_LIGHT
        border_bottom = ThemeColors.BORDER_DARK
        pressed_bg = ThemeColors.BG_MAIN

        if self._style_variant == "orange_glow":
            # Bordo arancione luminoso con testo arancione bold (es. Avvia, Aggiorna)
            text_color = ThemeColors.PRIMARY
            border_style = f"border: 1.5px solid {ThemeColors.PRIMARY};"
            hover_style = (
                f"background-color: {ThemeColors.BG_SURFACE_ALT}; "
                f"border: 1.5px solid {ThemeColors.PRIMARY_LIGHT}; "
                f"color: {ThemeColors.PRIMARY_LIGHT};"
            )
        elif self._style_variant == "orange_text":
            # Bordo morbido standard con testo arancione bold (es. Cancella)
            text_color = ThemeColors.PRIMARY
            border_style = (
                f"border-top: 1px solid {border_top}; "
                f"border-left: 1px solid {border_top}; "
                f"border-right: 1px solid {border_bottom}; "
                f"border-bottom: 1px solid {border_bottom};"
            )
            hover_style = (
                f"background-color: {ThemeColors.BG_SURFACE_ALT}; "
                f"color: {ThemeColors.PRIMARY_LIGHT};"
            )
        elif self._style_variant == "danger" or self._is_danger:
            text_color = ThemeColors.DANGER
            border_style = (
                f"border-top: 1px solid {border_top}; "
                f"border-left: 1px solid {border_top}; "
                f"border-right: 1px solid {border_bottom}; "
                f"border-bottom: 1px solid {border_bottom};"
            )
            hover_style = (
                f"background-color: {ThemeColors.DANGER_DARK}; "
                f"color: {ThemeColors.TEXT_PRIMARY};"
            )
        else:
            # Neutro standard (es. Fine Audio, Ferma)
            text_color = ThemeColors.TEXT_SECONDARY
            border_style = (
                f"border-top: 1px solid {border_top}; "
                f"border-left: 1px solid {border_top}; "
                f"border-right: 1px solid {border_bottom}; "
                f"border-bottom: 1px solid {border_bottom};"
            )
            hover_style = (
                f"background-color: {ThemeColors.BG_SURFACE_ALT}; "
                f"color: {ThemeColors.TEXT_PRIMARY};"
            )

        self._button.setStyleSheet(
            f"QPushButton {{ "
            f"  background-color: {bg}; "
            f"  color: {text_color}; "
            f"  {border_style} "
            f"  border-radius: 8px; "
            f"  padding: 6px {_HPAD}px; "
            f"  min-height: 26px; "
            f"  font-weight: 600; "
            f"}} "
            f"QPushButton:hover {{ "
            f"  {hover_style} "
            f"}} "
            f"QPushButton:pressed {{ "
            f"  background-color: {pressed_bg}; "
            f"  color: {text_color}; "
            f"  border-top: 1px solid {border_bottom}; "
            f"  border-left: 1px solid {border_bottom}; "
            f"  border-right: 1px solid {border_top}; "
            f"  border-bottom: 1px solid {border_top}; "
            f"  padding-top: 7px; "
            f"  padding-left: {_HPAD + 1}px; "
            f"}} "
            f"QPushButton:disabled {{ "
            f"  background-color: {ThemeColors.BG_SURFACE}; "
            f"  color: {ThemeColors.TEXT_DISABLED}; "
            f"  border: 1px solid {ThemeColors.BORDER}; "
            f"}}"
        )

    def set_status(self, state: StatusIndicator.State) -> None:
        """Aggiorna lo stato visivo dell'indicatore.

        Args:
            state: Nuovo stato del processo.
        """
        self._indicator.set_state(state)

    def setEnabled(self, enabled: bool) -> None:
        """Abilita o disabilita il pulsante.

        Args:
            enabled: True per abilitare, False per disabilitare.
        """
        self._button.setEnabled(enabled)
