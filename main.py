# main.py
"""UltraTranscribr — Punto di ingresso (orchestratore puro)."""
from __future__ import annotations

import logging
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from config.constants import AppMeta
from config.settings import Settings
from core.app_controller import AppController
from core.application_service import ApplicationService
from core.exceptions import GPUNotAvailableError
from ui.main_window import MainWindow
from ui.native.dictation_integration import DictationNativeIntegration
from ui.tray_icon import TrayIcon

LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 4


def setup_logging() -> None:
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


def install_process_signal_handlers(app: QApplication) -> QTimer:
    """Route terminal/process stop signals through the normal Qt shutdown path."""

    def request_quit(_signum, _frame) -> None:
        app.quit()

    signal.signal(signal.SIGINT, request_quit)
    signal.signal(signal.SIGTERM, request_quit)

    # Python dispatches signal handlers on the main interpreter thread. A small
    # Qt timer regularly returns control to Python while app.exec() is running,
    # so Ctrl+C remains reliable without a second event loop or polling thread.
    timer = QTimer(app)
    timer.setInterval(250)
    timer.timeout.connect(lambda: None)
    timer.start()
    return timer


def main() -> None:
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
    app.setQuitOnLastWindowClosed(False)
    interrupt_timer = install_process_signal_handlers(app)

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
    window = MainWindow(application=application)
    dictation_native = DictationNativeIntegration(application, app)

    icon_path = Path(__file__).parent / "assets" / "icons" / "icon.png"
    if not icon_path.exists():
        icon_path = Path(__file__).parent / "assets" / "icons" / "ultratranscribr.svg"

    if icon_path.exists():
        window_icon = QIcon(str(icon_path))
        window.setWindowIcon(window_icon)
        app.setWindowIcon(window_icon)

    tray = TrayIcon(parent=app, icon_path=str(icon_path) if icon_path.exists() else None)
    tray.show()
    tray.log_readiness()
    tray.show_window_requested.connect(window.show)
    tray.show_window_requested.connect(window.raise_)
    tray.show_window_requested.connect(window.activateWindow)
    tray.connect_start_action(window.on_start)
    tray.connect_stop_action(window.on_stop)
    tray.quit_requested.connect(window.force_quit)

    window.set_tray_icon(tray)
    window.show()
    QTimer.singleShot(0, dictation_native.start)

    logger.info("UltraTranscribr pronto (SYCL GPU)")
    exit_code = 1
    try:
        exit_code = app.exec()
    finally:
        # Keep the Python wrapper alive for the entire Qt loop; its QObject parent
        # owns the C++ timer, while this reference makes the lifetime explicit.
        del interrupt_timer
        try:
            dictation_native.close()
        finally:
            try:
                application.close()
            finally:
                controller.shutdown()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
