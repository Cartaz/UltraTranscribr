"""Renderer Qt per superfici Dark Neumorphism.

La sorgente di luce virtuale è sempre in alto a sinistra.
I rilievi usano highlight alto/sinistra e ombra basso/destra.
Gli input usano la direzione opposta per apparire incavati.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QLinearGradient, QPainter,
    QPainterPath, QPen, QBrush,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QLineEdit, QProgressBar,
    QPushButton, QTextEdit, QWidget, QTabBar,
)

from config.theme import theme


def _alpha(color_spec: str, alpha: int) -> QColor:
    color = QColor(color_spec)
    color.setAlpha(max(0, min(255, alpha)))
    return color


def _path_for_rect(rect, radius: int) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def _rounded_path(
    widget: QWidget,
    inset: float = 1.0,
    radius: int | None = None,
) -> QPainterPath:
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
    """Superficie estrusa morbida e chiaramente neumorfica."""
    m = max(2, int(margin))
    rect = widget.rect().adjusted(m, m, -m, -m)
    if rect.width() <= 4 or rect.height() <= 4:
        return

    base = _path_for_rect(rect, radius)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    depth = min(float(m), float(theme.shadow_offset))
    if not strong:
        depth *= 0.62

    steps = max(10, int(depth * 2.6))
    light_alpha = (
        theme.raised_light_alpha
        if strong else int(theme.raised_light_alpha * 0.56)
    )
    dark_alpha = (
        theme.raised_dark_alpha
        if strong else int(theme.raised_dark_alpha * 0.58)
    )

    # Ombre esterne stratificate: l'ordine è importante.
    for i in range(steps, 0, -1):
        t = i / steps
        off = depth * t
        fade = (1.0 - t) ** 0.62

        light_shape = _path_for_rect(
            rect.translated(-off, -off),
            radius + int(off * 0.42),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(_alpha(
            theme.shadow_light,
            max(2, int(light_alpha * fade * 0.55)),
        )))
        painter.drawPath(light_shape.subtracted(base))

        dark_shape = _path_for_rect(
            rect.translated(off, off),
            radius + int(off * 0.42),
        )
        painter.setBrush(QBrush(_alpha(
            theme.shadow_dark,
            max(3, int(dark_alpha * fade * 0.62)),
        )))
        painter.drawPath(dark_shape.subtracted(base))

    # Materiale leggermente modellato, senza effetto glass.
    fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
    fill.setColorAt(0.0, theme.qcolor(theme.bg_surface_alt))
    fill.setColorAt(0.34, theme.qcolor(theme.bg))
    fill.setColorAt(1.0, theme.qcolor(theme.bg))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(fill))
    painter.drawPath(base)

    # Microscopico highlight di bordo sul lato illuminato.
    painter.setPen(QPen(_alpha(theme.shadow_light, 62 if strong else 34), 1.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(base)

    painter.restore()


def _paint_external_relief(
    painter: QPainter,
    base: QPainterPath,
    radius: int,
    depth: float,
    light_alpha: int,
    dark_alpha: int,
    *,
    bottom_shadow: bool = True,
) -> None:
    steps = max(8, int(depth * 2.4))
    for i in range(steps, 0, -1):
        t = i / steps
        off = depth * t
        fade = (1.0 - t) ** 0.64

        light_shape = base.translated(-off, -off)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(_alpha(
            theme.shadow_light,
            max(2, int(light_alpha * fade * 0.48)),
        )))
        painter.drawPath(light_shape.subtracted(base))

        if bottom_shadow:
            dark_shape = base.translated(off, off)
            painter.setBrush(QBrush(_alpha(
                theme.shadow_dark,
                max(3, int(dark_alpha * fade * 0.56)),
            )))
            painter.drawPath(dark_shape.subtracted(base))


def _paint_inset_surface(
    painter: QPainter,
    widget: QWidget,
    radius: int,
) -> None:
    """Superficie incavata con ombra interna alto/sinistra."""
    rect = widget.rect().adjusted(1, 1, -1, -1)
    if rect.width() <= 3 or rect.height() <= 3:
        return
    path = _path_for_rect(rect, radius)

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(theme.qcolor(theme.bg_surface)))
    painter.drawPath(path)

    painter.setClipPath(path)
    depth = 7.0
    steps = 10

    for i in range(steps, 0, -1):
        t = i / steps
        off = depth * t
        fade = (1.0 - t) ** 0.56

        # Scuro in alto/sinistra.
        dark_rect = rect.translated(-off, -off)
        painter.setPen(QPen(
            _alpha(theme.shadow_dark, max(
                10, int(theme.inset_dark_alpha * fade * 0.72)
            )),
            1.0 + t * 2.1,
        ))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(_path_for_rect(
            dark_rect, radius + int(off * 0.42)
        ))

        # Luce riflessa in basso/destra.
        light_rect = rect.translated(off, off)
        painter.setPen(QPen(
            _alpha(theme.shadow_light, max(
                7, int(theme.inset_light_alpha * fade * 0.55)
            )),
            1.0 + t * 1.8,
        ))
        painter.drawPath(_path_for_rect(
            light_rect, radius + int(off * 0.42)
        ))

    shade = QLinearGradient(rect.topLeft(), rect.bottomRight())
    shade.setColorAt(0.0, _alpha(theme.shadow_dark, 54))
    shade.setColorAt(0.40, QColor(0, 0, 0, 0))
    shade.setColorAt(0.72, QColor(0, 0, 0, 0))
    shade.setColorAt(1.0, _alpha(theme.shadow_light, 30))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.fillPath(path, QBrush(shade))
    painter.restore()


def _paint_focus(
    painter: QPainter,
    widget: QWidget,
    radius: int,
) -> None:
    painter.setPen(QPen(theme.qcolor(theme.accent), theme.focus_width))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(_rounded_path(
        widget, theme.focus_inset, radius
    ))


class NeumorphicButton(QPushButton):
    """Pulsante rialzato, incavato durante la pressione."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        danger: bool = False,
        variant: str = "neutral",
    ) -> None:
        super().__init__(text, parent)
        self._hovered = False
        self._pressed = False
        self._variant = "danger" if danger else variant
        self.setFont(QFont(
            theme.font_family,
            theme.font_size,
            QFont.Weight.Medium,
        ))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self.update()

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

        if not self.isEnabled():
            _paint_raised_surface(
                painter, self, theme.radius_sm, 5, strong=False
            )
        elif self._pressed:
            _paint_inset_surface(painter, self, theme.radius_sm)
        else:
            _paint_raised_surface(
                painter,
                self,
                theme.radius_sm,
                5,
                strong=not self._hovered,
            )

        if self._variant in {"orange_glow", "orange_text", "accent"}:
            text_color = theme.accent
        elif self._variant == "danger":
            text_color = theme.danger
        else:
            text_color = (
                theme.text_primary if self._hovered
                else theme.text_secondary
            )
        if not self.isEnabled():
            text_color = theme.text_disabled

        painter.setPen(theme.qcolor(text_color))
        painter.setFont(self.font())
        painter.drawText(
            self.rect().adjusted(10, 0, -10, 0),
            Qt.AlignmentFlag.AlignCenter,
            self.text(),
        )

        if self.hasFocus() and self.isEnabled():
            _paint_focus(painter, self, theme.radius_sm)
        elif (
            self.isEnabled()
            and self._hovered
            and self._variant == "orange_glow"
        ):
            painter.setPen(QPen(_alpha(theme.accent, 190), 1.35))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(_rounded_path(
                self, 2.0, theme.radius_sm
            ))

        painter.end()


class NeumorphicComboBox(QComboBox):
    """ComboBox realmente incavato, con indicatore arancione minimale."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrame(False)
        self.setFont(QFont(theme.font_family, theme.font_size))
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        _paint_inset_surface(painter, self, theme.radius_sm)

        text_color = (
            theme.text_primary if self.isEnabled()
            else theme.text_disabled
        )
        painter.setPen(theme.qcolor(text_color))
        painter.setFont(self.font())

        text_rect = self.rect().adjusted(12, 0, -30, 0)
        fm = QFontMetrics(self.font())
        text = fm.elidedText(
            self.currentText(),
            Qt.TextElideMode.ElideRight,
            max(0, text_rect.width()),
        )
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )

        # Piccolo indicatore quadrato come nel mockup approvato.
        side = 7
        x = self.width() - 18
        y = (self.height() - side) // 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor(
            theme.accent if self.isEnabled() else theme.text_disabled
        ))
        painter.drawRoundedRect(x, y, side, side, 2, 2)

        if self.hasFocus() and self.isEnabled():
            _paint_focus(painter, self, theme.radius_sm)
        painter.end()


class NeumorphicLineEdit(QLineEdit):
    """Campo monoriga incavato."""

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
            _paint_inset_surface(painter, self, theme.radius_sm)
            if self.hasFocus():
                _paint_focus(painter, self, theme.radius_sm)
            painter.end()
        super().paintEvent(event)


class NeumorphicTextEdit(QTextEdit):
    """Campo multilinea incavato."""

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
    pass


class NeumorphicProgressBar(QProgressBar):
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_inset_surface(painter, self, theme.radius_sm)
        if self.maximum() > self.minimum():
            ratio = (
                (self.value() - self.minimum())
                / (self.maximum() - self.minimum())
            )
            chunk = self.rect().adjusted(
                theme.progress_inset,
                theme.progress_inset,
                -theme.progress_inset,
                -theme.progress_inset,
            )
            chunk.setWidth(max(0, int(chunk.width() * ratio)))
            if chunk.width() > 0:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(theme.qcolor(theme.accent))
                painter.drawRoundedRect(
                    chunk, 3, 3
                )
        painter.end()


class NeumorphicPage(QWidget):
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if painter.isActive():
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            _paint_raised_surface(
                painter, self, theme.radius_lg,
                theme.page_shadow_margin, strong=True
            )
            painter.end()


class NeumorphicCard(QWidget):
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if painter.isActive():
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            _paint_raised_surface(
                painter, self, theme.radius_lg,
                theme.card_shadow_margin, strong=True
            )
            painter.end()


class NeumorphicFieldLabel(QWidget):
    def __init__(
        self, text: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._text = text
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
        _paint_inset_surface(painter, self, theme.radius_sm)
        painter.setPen(theme.qcolor(theme.text_primary))
        painter.setFont(self.font())
        painter.drawText(
            self.rect().adjusted(12, 0, -12, 0),
            Qt.AlignmentFlag.AlignVCenter,
            self._text,
        )
        painter.end()


class NeumorphicTabBar(QTabBar):
    """Disponibile per futuri usi; non impone dimensioni al layout."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setUsesScrollButtons(False)
        self.setFont(QFont(theme.font_family, theme.font_size))


class NeumorphicCheckBox(QCheckBox):
    """Checkbox custom senza cambiare le metriche imposte dal layout."""

    def __init__(
        self, text: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(text, parent)
        self.setFont(QFont(theme.font_family, theme.font_size))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
