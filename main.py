# main.py
"""UltraTranscribr — Punto di ingresso (orchestratore puro).

Inizializza l'applicazione Qt, verifica il backend SYCL, carica le
impostazioni, crea il controller, i servizi applicativi, la finestra
principale e l'icona tray, e avvia il loop degli eventi. Nessuna logica
applicativa in questo file.

Usage:
    python main.py
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from config.constants import AppMeta
from config.settings import Settings
from core.app_controller import AppController
from core.application_service import ApplicationService
from core.exceptions import GPUNotAvailableError
from ui.main_window import MainWindow
from ui.tray_icon import TrayIcon


LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 4


def setup_logging() -> None:
    """Configura console e file log XDG con rotazione limitata."""
    AppMeta.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler(
                AppMeta.LOG_PATH,
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            ),
        ],
    )


def main() -> None:
    """Punto di ingresso dell'applicazione — orchestratore puro."""
    setup_logging()
    logger = logging.getLogger("UltraTranscribr")
    logger.info("Avvio UltraTranscribr (SYCL)...")

    settings = Settings.load()
    logger.info(
        "Impostazioni caricate — model=%s, device=%s, source=%s, lang=%s",
        settings.model_size,
        settings.device,
        settings.audio_source,
        settings.language,
    )

    app = QApplication(sys.argv)
    app.setApplicationName(AppMeta.NAME)
    app.setApplicationDisplayName(AppMeta.NAME)
    app.setDesktopFileName(AppMeta.ID)
    app.setQuitOnLastWindowClosed(True)

    try:
        controller = AppController(settings=settings)
    except GPUNotAvailableError as exc:
        logger.critical("GPU SYCL non disponibile: %s", exc.message)
        QMessageBox.critical(
            None,
            "GPU non disponibile",
            f"{exc.message}\n\n{exc.detail}\n\n"
            "UltraTranscribr richiede una GPU Intel Arc con driver SYCL.",
        )
        sys.exit(1)

    application = ApplicationService(controller)
    window = MainWindow(controller=controller, application=application)

    icon_path = Path(__file__).parent / "assets" / "icons" / "icon.png"
    if not icon_path.exists():
        icon_path = Path(__file__).parent / "assets" / "icons" / "ultratranscribr.svg"

    if icon_path.exists():
        window_icon = QIcon(str(icon_path))
        window.setWindowIcon(window_icon)
        app.setWindowIcon(window_icon)

    tray = TrayIcon(
        parent=app,
        icon_path=str(icon_path) if icon_path.exists() else None,
    )
    tray.show()

    tray.show_window_requested.connect(window.show)
    tray.show_window_requested.connect(window.raise_)
    tray.show_window_requested.connect(window.activateWindow)
    tray.connect_start_action(window.on_start)
    tray.connect_stop_action(window.on_stop)
    tray.quit_requested.connect(window.force_quit)

    window.set_tray_icon(tray)
    window.show()

    logger.info("UltraTranscribr pronto (SYCL GPU)")
    exit_code = 1
    try:
        exit_code = app.exec()
    finally:
        application.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
