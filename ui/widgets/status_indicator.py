# ui/widgets/status_indicator.py
"""Indicatore di stato animato — punto colorato con pulsazione.

Mostra visivamente lo stato di un processo in background tramite
un punto colorato (diametro 8px) con animazione pulsante per i
processi attivi (opacity oscillante tra 0.5 e 1.0).

Classes:
    StatusIndicator: Widget indicatore di stato animato.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPainter, QColor, QBrush
from PySide6.QtWidgets import QWidget

from config.theme import ThemeColors
from config.constants import UIConstraints


class StatusIndicator(QWidget):
    """Indicatore di stato animato — punto colorato con pulsazione.

    L'animazione pulsante mostra visivamente lo stato del processo:
    uno stato attivo ha opacity oscillante, uno stato inattivo e fisso.

    Attributes:
        State: Enum degli stati supportati.
    """

    class State(Enum):
        """Stati visivi dell'indicatore."""

        RUNNING = "running"
        STOPPED = "stopped"
        ERROR = "error"
        PAUSED = "paused"
        BUFFERING = "buffering"
        LOADING = "loading"
        IDLE = "idle"
        COMPLETED = "completed"

    # Mappa stati → colori del tema
    _STATE_COLORS: dict[State, str] = {
        State.RUNNING: ThemeColors.STATUS_RUNNING,
        State.STOPPED: ThemeColors.STATUS_STOPPED,
        State.ERROR: ThemeColors.STATUS_ERROR,
        State.PAUSED: ThemeColors.STATUS_PAUSED,
        State.BUFFERING: ThemeColors.STATUS_BUFFERING,
        State.LOADING: ThemeColors.STATUS_LOADING,
        State.IDLE: ThemeColors.STATUS_STOPPED,
        State.COMPLETED: ThemeColors.STATUS_RUNNING,
    }

    # Stati che richiedono animazione pulsante
    _ANIMATED_STATES = {State.RUNNING, State.BUFFERING, State.LOADING}

    def __init__(self, parent: QWidget | None = None) -> None:
        """Inizializza l'indicatore di stato.

        Args:
            parent: Widget genitore.
        """
        super().__init__(parent)
        self._state = self.State.IDLE
        self._opacity = 1.0
        self._color = QColor(self._STATE_COLORS[self.State.IDLE])

        diameter = UIConstraints.STATUS_DOT_DIAMETER
        self.setFixedSize(diameter, diameter)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(50)
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_direction = 1
        self._pulse_step = 0

    def set_state(self, state: State) -> None:
        """Aggiorna lo stato visivo dell'indicatore.

        Args:
            state: Nuovo stato del processo.
        """
        self._state = state
        color_hex = self._STATE_COLORS.get(state, ThemeColors.STATUS_STOPPED)
        self._color = QColor(color_hex)
        self._opacity = 1.0

        if state in self._ANIMATED_STATES:
            self._pulse_step = 0
            self._pulse_direction = 1
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
        self.update()

    def _pulse_tick(self) -> None:
        """Aggiorna l'opacity per l'animazione pulsante."""
        period_ms = ThemeColors.ANIM_PULSE_PERIOD_MS
        steps = period_ms // self._pulse_timer.interval()
        delta = 0.5 / steps
        self._opacity += delta * self._pulse_direction

        if self._opacity >= 1.0:
            self._opacity = 1.0
            self._pulse_direction = -1
        elif self._opacity <= 0.5:
            self._opacity = 0.5
            self._pulse_direction = 1

        self.update()

    def paintEvent(self, event) -> None:
        """Disegna il punto colorato con l'opacity corrente e bagliore neumorfico."""
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        diameter = UIConstraints.STATUS_DOT_DIAMETER
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        r = diameter / 2.0

        # Incavo di sfondo (socket neumorfico)
        socket_color = QColor(ThemeColors.BG_SURFACE)
        painter.setBrush(QBrush(socket_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(cx - r - 1, cy - r - 1, (r + 1) * 2, (r + 1) * 2)

        # Bagliore soffuso per stati attivi
        if self._state in self._ANIMATED_STATES:
            glow = QColor(self._color)
            glow.setAlphaF(0.25 * self._opacity)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(cx - r - 2, cy - r - 2, (r + 2) * 2, (r + 2) * 2)

        # LED colorato
        color = QColor(self._color)
        color.setAlphaF(self._opacity)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)
        painter.end()
