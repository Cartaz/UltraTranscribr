# ui/widgets/card.py
"""Card con intestazione in maiuscoletto per il raggruppamento di azioni.

Ogni card ha sfondo Neumorphic BG_CARD, bordi morbidi con doppia
ombra direzionale (luce in alto a sinistra, ombra profonda in basso a destra),
padding interno e margine esterno. L'intestazione usa small caps con letter-spacing.

Classes:
    Card: Widget card con intestazione etichettata e rilievo neumorfico.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from config.constants import UIConstraints
from config.theme import ThemeColors, theme
from ui.widgets.neumorphic import _paint_raised_surface


class Card(QWidget):
    """Card con intestazione in maiuscoletto e rilievo neumorfico.

    La card racchiude widget figli in un contenitore visivamente
    estruso con doppia sorgente di luce/ombra neumorfica.

    Args:
        title: Testo dell'intestazione della card.
        parent: Widget genitore.
    """

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        """Inizializza la card con il titolo dato.

        Args:
            title: Testo dell'intestazione.
            parent: Widget genitore.
        """
        super().__init__(parent)
        self._setup_ui(title)

    def _setup_ui(self, title: str) -> None:
        """Configura il layout e lo stile della card.

        Args:
            title: Testo dell'intestazione.
        """
        padding = UIConstraints.CARD_PADDING
        margin = UIConstraints.CARD_MARGIN

        self.setObjectName("cardWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(margin, margin, margin, margin)

        inner = QVBoxLayout()
        inner.setContentsMargins(padding, padding, padding, padding)
        inner.setSpacing(8)

        header = QLabel(title)
        header.setFont(QFont(ThemeColors.FONT_FAMILY, 11, QFont.Weight.DemiBold))
        header.setStyleSheet(
            f"color: {ThemeColors.TEXT_SECONDARY}; "
            f"letter-spacing: 0.8px; "
            f"border: none; "
            f"background: transparent; "
            f"padding: 0; "
            f"margin: 0 0 2px 0;"
        )
        inner.addWidget(header)

        self._content_layout = QVBoxLayout()
        self._content_layout.setSpacing(8)
        inner.addLayout(self._content_layout)

        outer.addLayout(inner)

    def paintEvent(self, event) -> None:
        """Disegna la superficie estrusa neumorfica con luce e ombra opposte."""
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_raised_surface(
            painter,
            self,
            theme.radius_lg,
            UIConstraints.CARD_MARGIN,
            strong=True,
        )
        painter.end()

    def content_layout(self) -> QVBoxLayout:
        """Restituisce il layout di contenuto per aggiungere widget.

        Returns:
            Il QVBoxLayout interno in cui inserire i widget figli.
        """
        return self._content_layout
