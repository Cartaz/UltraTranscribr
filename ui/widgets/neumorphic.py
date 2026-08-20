"""Widget Qt custom per il tema neumorfico di UltraTranscribr.

Il rendering usa esclusivamente API Qt/Python: QPainter, gradienti e palette.
Le superfici rialzate hanno sempre due sorgenti visive opposte:
luce morbida in alto a sinistra e ombra morbida in basso a destra.
I campi editabili usano invece lo stesso principio invertito, dentro il bordo.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QBrush,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGraphicsOpacityEffect, QLineEdit, QProgressBar,
    QPushButton, QTextEdit, QWidget, QTabBar,
)

from config.theme import theme


def _alpha(hex_value: str, alpha: int) -> QColor:
    color = QColor(hex_value)
    color.setAlpha(max(0, min(255, alpha)))
    return color


def _path_for_rect(rect, radius: int) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def _rounded_path(widget: QWidget, inset: float = 1.0, radius: int | None = None) -> QPainterPath:
    r = radius if radius is not None else theme.radius_md
    rect = widget.rect().adjusted(inset, inset, -inset, -inset)
    return _path_for_rect(rect, r)


def _paint_raised_surface(
    painter: QPainter,
    widget: QWidget,
    radius: int,
    margin: int,
    *,
    strong: bool = True,
) -> None:
    """Disegna una superficie estrusa con luce/ombra *solo all'esterno*.

    La superficie resta uniforme. Le due sorgenti luminose vengono costruite
    come fasce esterne al perimetro reale: la parte che ricadrebbe dentro la
    superficie viene sottratta tramite QPainterPath.subtracted(). In questo
    modo non compaiono bordi chiari/scuri sui quattro lati interni, che
    trasformerebbero il rilievo in un incavo.
    """
    m = max(2, int(margin))
    rect = widget.rect().adjusted(m, m, -m, -m)
    if rect.width() <= 4 or rect.height() <= 4:
        return

    base = _path_for_rect(rect, radius)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Materiale uniforme: nessun gradiente/bordo interno.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(theme.qcolor(theme.bg)))
    painter.drawPath(base)

    depth = max(4.0, min(float(m), float(theme.shadow_offset)))
    if not strong:
        depth *= 0.58

    steps = max(6, int(depth * 1.8))
    light_alpha = theme.raised_light_alpha if strong else int(theme.raised_light_alpha * 0.55)
    dark_alpha = theme.raised_dark_alpha if strong else int(theme.raised_dark_alpha * 0.55)

    # Ogni banda è una differenza geometrica: shifted - base.
    # Quindi viene dipinta esclusivamente nello spazio esterno.
    for i in range(steps, 0, -1):
        t = i / steps
        off = depth * t
        fade = (1.0 - t) ** 0.72
        band_width = max(1.0, depth / steps * 2.1)

        # Highlight: alto/sinistra.
        light_shape = _path_for_rect(
            rect.translated(-off, -off),
            radius + int(off * 0.45),
        )
        light_outer = light_shape.subtracted(base)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(_alpha(theme.shadow_light, max(2, int(light_alpha * fade * 0.48)))))
        painter.drawPath(light_outer)

        # Ombra: basso/destra.
        dark_shape = _path_for_rect(
            rect.translated(off, off),
            radius + int(off * 0.45),
        )
        dark_outer = dark_shape.subtracted(base)
        painter.setBrush(QBrush(_alpha(theme.shadow_dark, max(3, int(dark_alpha * fade * 0.42)))))
        painter.drawPath(dark_outer)

    painter.restore()


def _paint_external_relief(painter: QPainter, base: QPainterPath, radius: int, depth: float, light_alpha: int, dark_alpha: int, *, bottom_shadow: bool = True) -> None:
    """Applica rilievo esclusivamente fuori da una geometria già definita."""
    steps = max(6, int(depth * 1.8))
    for i in range(steps, 0, -1):
        t = i / steps
        off = depth * t
        fade = (1.0 - t) ** 0.72
        light_shape = base.translated(-off, -off)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(_alpha(theme.shadow_light, max(2, int(light_alpha * fade * 0.48)))))
        painter.drawPath(light_shape.subtracted(base))
        if bottom_shadow:
            dark_shape = base.translated(off, off)
            painter.setBrush(QBrush(_alpha(theme.shadow_dark, max(3, int(dark_alpha * fade * 0.42)))))
            painter.drawPath(dark_shape.subtracted(base))


def _paint_inset_surface(painter: QPainter, widget: QWidget, radius: int) -> None:
    """Disegna un incavo: scuro in alto/sinistra, luce in basso/destra."""
    rect = widget.rect().adjusted(1, 1, -1, -1)
    path = _path_for_rect(rect, radius)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(theme.qcolor(theme.bg)))
    painter.drawPath(path)

    painter.save()
    painter.setClipPath(path)
    depth = 5
    steps = 6
    for i in range(steps, 0, -1):
        t = i / steps
        offset = depth * t
        alpha_dark = int(theme.inset_dark_alpha * (1.0 - t * 0.68))
        alpha_light = int(theme.inset_light_alpha * (1.0 - t * 0.68))

        # Ombra interna: bordo scuro rivolto verso alto/sinistra.
        dark_rect = rect.translated(-offset, -offset)
        painter.setPen(QPen(_alpha(theme.shadow_dark, max(10, alpha_dark)), max(1.0, 1.0 + t * 1.8), Qt.PenStyle.SolidLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(_path_for_rect(dark_rect, radius + int(offset * 0.5)))

        # Luce interna: bordo chiaro rivolto verso basso/destra.
        light_rect = rect.translated(offset, offset)
        painter.setPen(QPen(_alpha(theme.shadow_light, max(8, alpha_light)), max(1.0, 1.0 + t * 1.8), Qt.PenStyle.SolidLine))
        painter.drawPath(_path_for_rect(light_rect, radius + int(offset * 0.5)))

    # Gradiente appena percettibile che completa l'illusione di concavità.
    dark = QLinearGradient(rect.topLeft(), rect.bottomRight())
    dark.setColorAt(0.0, _alpha(theme.shadow_dark, 34))
    dark.setColorAt(0.32, QColor(0, 0, 0, 0))
    dark.setColorAt(0.72, QColor(0, 0, 0, 0))
    dark.setColorAt(1.0, _alpha(theme.shadow_light, 24))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.fillPath(path, QBrush(dark))
    painter.restore()


def _paint_focus(painter: QPainter, widget: QWidget, radius: int) -> None:
    painter.setPen(QPen(theme.qcolor(theme.accent), theme.focus_width))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(_rounded_path(widget, theme.focus_inset, radius))


class NeumorphicButton(QPushButton):
    """Pulsante estruso: luce + ombra in riposo, incavo quando premuto."""

    def __init__(self, text: str = "", parent: QWidget | None = None, *, danger: bool = False) -> None:
        super().__init__(text, parent)
        self._hovered = False
        self._pressed = False
        self._danger = danger
        self.setFont(QFont(theme.font_family, theme.font_size, QFont.Weight.Medium))
        self.setMinimumHeight(theme.control_height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self._sync_effect()

    def _sync_effect(self) -> None:
        if not self.isEnabled():
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(theme.disabled_opacity)
            self.setGraphicsEffect(effect)
        else:
            self.setGraphicsEffect(None)
        self.update()

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self._sync_effect()

    def enterEvent(self, event: QEvent) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self._pressed = False
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.isEnabled() and not self._pressed:
            # Hover: meno profondità, ma entrambe le luci rimangono presenti.
            margin = 3 if self._hovered else 5
            _paint_raised_surface(painter, self, theme.radius_sm, margin, strong=not self._hovered)
        else:
            _paint_inset_surface(painter, self, theme.radius_sm)

        text_color = theme.danger if self._danger else theme.accent
        if not self.isEnabled():
            text_color = theme.text_disabled
        painter.setPen(theme.qcolor(text_color))
        painter.setFont(self.font())
        dy = 1 if self._pressed else 0
        painter.drawText(self.rect().adjusted(10, dy, -10, dy), Qt.AlignmentFlag.AlignCenter, self.text())

        if self.hasFocus() and self.isEnabled():
            _paint_focus(painter, self, theme.radius_sm)
        painter.end()


class NeumorphicTextEdit(QTextEdit):
    """Campo multilinea incavato; usato per la trascrizione."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameStyle(0)
        self.setAutoFillBackground(False)
        self.setFont(QFont(theme.font_family, theme.font_size))
        pal = self.viewport().palette()
        pal.setColor(pal.ColorRole.Base, QColor(0, 0, 0, 0))
        pal.setColor(pal.ColorRole.Text, theme.qcolor(theme.text_primary))
        self.viewport().setPalette(pal)
        self.viewport().setAutoFillBackground(False)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if painter.isActive():
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            _paint_inset_surface(painter, self, theme.radius_md)
            if self.hasFocus():
                _paint_focus(painter, self, theme.radius_md)
            painter.end()
        super().paintEvent(event)


class NeumorphicTranscriptionField(NeumorphicTextEdit):
    """Campo dedicato alla trascrizione: l'unica superficie volutamente incavata."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transcriptionField")
        self.setViewportMargins(4, 4, 4, 4)


class NeumorphicLineEdit(QLineEdit):
    """Campo a riga singola incavato."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrame(False)
        self.setAutoFillBackground(False)
        self.setFont(QFont(theme.font_family, theme.font_size))
        pal = self.palette()
        pal.setColor(pal.ColorRole.Base, QColor(0, 0, 0, 0))
        pal.setColor(pal.ColorRole.Text, theme.qcolor(theme.text_primary))
        self.setPalette(pal)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if painter.isActive():
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            _paint_raised_surface(painter, self, theme.radius_sm, 4, strong=True)
            if self.hasFocus():
                _paint_focus(painter, self, theme.radius_sm)
            painter.end()
        super().paintEvent(event)


class NeumorphicComboBox(QComboBox):
    """ComboBox con incavo costante e focus accentato."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrame(False)
        self.setAutoFillBackground(False)
        self.setFont(QFont(theme.font_family, theme.font_size))
        pal = self.palette()
        pal.setColor(pal.ColorRole.Base, QColor(0, 0, 0, 0))
        pal.setColor(pal.ColorRole.Button, QColor(0, 0, 0, 0))
        pal.setColor(pal.ColorRole.Text, theme.qcolor(theme.text_primary))
        self.setPalette(pal)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if painter.isActive():
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            _paint_raised_surface(painter, self, theme.radius_sm, 4, strong=True)
            if self.hasFocus():
                _paint_focus(painter, self, theme.radius_sm)
            painter.end()
        super().paintEvent(event)


class NeumorphicProgressBar(QProgressBar):
    """Progress bar con pista incavata e avanzamento accentato."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_raised_surface(painter, self, theme.radius_sm, 4, strong=True)
        if self.maximum() > self.minimum():
            ratio = (self.value() - self.minimum()) / (self.maximum() - self.minimum())
            chunk = self.rect().adjusted(theme.progress_inset, theme.progress_inset,
                                         -theme.progress_inset, -theme.progress_inset)
            chunk.setWidth(max(0, int(chunk.width() * ratio)))
            if chunk.width() > 0:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(theme.qcolor(theme.accent))
                painter.drawRoundedRect(chunk, theme.radius_sm - 4, theme.radius_sm - 4)
        painter.end()


class NeumorphicPage(QWidget):
    """Contenitore principale rialzato della scheda Live/File."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_raised_surface(painter, self, theme.radius_lg, theme.page_shadow_margin, strong=True)
        painter.end()


class NeumorphicCard(QWidget):
    """Sezione interna rialzata, con doppia ombra coerente con la pagina."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_raised_surface(painter, self, theme.radius_lg, theme.card_shadow_margin, strong=True)
        painter.end()


class NeumorphicFieldLabel(QWidget):
    """Piccola superficie incavata usata per il percorso file."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self.setMinimumHeight(theme.control_height)
        self.setFont(QFont(theme.font_family, theme.font_size))

    def setText(self, text: str) -> None:
        self._text = text
        self.update()

    def text(self) -> str:
        return self._text

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_raised_surface(painter, self, theme.radius_sm, 4, strong=True)
        painter.setPen(theme.qcolor(theme.text_primary))
        painter.setFont(self.font())
        painter.drawText(self.rect().adjusted(12, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter, self._text)
        painter.end()


class NeumorphicTabBar(QTabBar):
    """Linguette unite alla scheda sottostante."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setFont(QFont(theme.font_family, theme.font_size))
        self.setUsesScrollButtons(False)
        self.setDocumentMode(True)
        self.setMinimumHeight(theme.tab_height)
        self.setContentsMargins(0, 0, 0, 0)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index in range(self.count()):
            selected = index == self.currentIndex()
            tab = self.tabRect(index)
            rect = tab.adjusted(3, 3, -3, 0)
            path = QPainterPath()
            path.addRoundedRect(rect, theme.radius_sm, theme.radius_sm)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(theme.qcolor(theme.bg)))
            painter.drawPath(path)

            if selected:
                # Il tab attivo è rialzato rispetto al fondo, ma resta aperto
                # sul lato inferiore per continuare visivamente nella pagina.
                _paint_external_relief(
                    painter, path, theme.radius_sm, 4.0,
                    theme.raised_light_alpha, theme.raised_dark_alpha,
                    bottom_shadow=False,
                )

            painter.setPen(theme.qcolor(theme.text_primary if selected else theme.text_secondary))
            painter.setFont(self.font())
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.tabText(index))
        painter.end()


class NeumorphicCheckBox(QCheckBox):
    """Checkbox coerente con il materiale neumorfico, senza QSS."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setFont(QFont(theme.font_family, theme.font_size))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(theme.control_height)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = self.rect().adjusted(5, (self.height() - 18) // 2, -1, -(self.height() - 18) // 2)
        box.setWidth(18)
        box.setHeight(18)
        path = _path_for_rect(box, 9)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(theme.qcolor(theme.bg)))
        painter.drawPath(path)
        _paint_external_relief(
            painter, path, 9, 4.0, 155, 145, bottom_shadow=True
        )
        if self.isChecked():
            painter.setPen(QPen(theme.qcolor(theme.accent), 2))
            painter.drawArc(box.adjusted(4, 4, -4, -4), 45 * 16, 90 * 16)
            painter.drawArc(box.adjusted(4, 4, -4, -4), -45 * 16, 90 * 16)
        if self.hasFocus():
            painter.setPen(QPen(theme.qcolor(theme.accent), theme.focus_width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box.adjusted(-2, -2, 2, 2), 10, 10)
        painter.setPen(theme.qcolor(theme.text_primary if self.isEnabled() else theme.text_disabled))
        painter.setFont(self.font())
        painter.drawText(self.rect().adjusted(30, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, self.text())
        painter.end()
