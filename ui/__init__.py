"""Pacchetto UI — interfaccia utente dell'applicazione UltraTranscribr.

Il livello UI importa da core/ e config/ ma non da main.py.

Exports:
    EventBridge: Bridge EventBus -> Signal Qt.
    MainWindow: Finestra principale dell'applicazione.
    TrayIcon: Icona nel system tray con menu contestuale.
"""

from ui.event_bridge import EventBridge
from ui.main_window import MainWindow
from ui.tray_icon import TrayIcon

__all__ = [
    "EventBridge",
    "MainWindow",
    "TrayIcon",
]
