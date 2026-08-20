# ui/widgets/shortcut_badge.py
"""Badge scorciatoia tastiera per pulsanti d'azione.

Mostra la combinazione di tasti come piccolo badge incavato con sfondo
semi-trasparente, testo centrato e bordi morbidi neumorfici.
Conforme al design Neumorphic Dark con token semantici da config/theme.py.

La larghezza minima è calcolata rispetto al testo più lungo
("Ctrl+D") con 10 px di padding orizzontale per lato.

Classes:
    ShortcutBadge: Badge visivo per scorciatoia tastiera.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QLabel, QWidget

from config.theme import ThemeColors
from config.constants import UIConstraints

# Testo di riferimento per il calcolo della larghezza minima del badge
_BADGE_REF_TEXT = "Ctrl+D"
_BADGE_HPAD = 10  # padding orizzontale per lato (px)


class ShortcutBadge(QLabel):
    """Badge visivo per scorciatoia tastiera.

    Mostra la combinazione di tasti (es. "Ctrl+S") con stile coerente
    al tema Neumorphic Dark. Il badge ha forma a pillola incavata
    con sfondo attenuato e testo di supporto ben contrastato.

    La larghezza minima è calibrata su "Ctrl+D" + 10 px per lato,
    così tutti i badge hanno la stessa larghezza compatta.

    Args:
        shortcut: Stringa della scorciatoia (es. "Ctrl+R").
        parent: Widget genitore.
    """

    def __init__(
        self,
        shortcut: str,
        parent: QWidget | None = None,
    ) -> None:
        """Inizializza il badge scorciatoia.

        Args:
            shortcut: Stringa della scorciatoia tastiera.
            parent: Widget genitore.
        """
        super().__init__(shortcut, parent)
        self._shortcut_text = shortcut
        self._setup_style()

    def _setup_style(self) -> None:
        """Applica lo stile Neumorphic Dark al badge e imposta la larghezza minima."""
        font_size = UIConstraints.SHORTCUT_BADGE_FONT_SIZE
        font = QFont(ThemeColors.FONT_FAMILY, font_size, QFont.Weight.Medium)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(font)

        # Larghezza minima calcolata su "Ctrl+D" + 10px per lato
        fm = QFontMetrics(font)
        ref_w = fm.horizontalAdvance(_BADGE_REF_TEXT) + 2 * _BADGE_HPAD + 2  # +2 border
        self.setMinimumWidth(ref_w)

        self.setStyleSheet(
            f"background-color: {ThemeColors.BG_SURFACE}; "
            f"color: {ThemeColors.TEXT_SECONDARY}; "
            f"border-top: 1px solid {ThemeColors.BORDER_DARK}; "
            f"border-left: 1px solid {ThemeColors.BORDER_DARK}; "
            f"border-right: 1px solid {ThemeColors.BORDER_LIGHT}; "
            f"border-bottom: 1px solid {ThemeColors.BORDER_LIGHT}; "
            f"border-radius: 5px; "
            f"padding: 2px {_BADGE_HPAD}px;"
        )
