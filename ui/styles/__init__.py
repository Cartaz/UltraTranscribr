# ui/styles/__init__.py
"""Pacchetto stili QSS per UltraTranscribr."""

from ui.styles.breeze_dark import build_stylesheet
from ui.styles.components import status_color, status_label

__all__ = [
    "build_stylesheet",
    "status_color",
    "status_label",
]
