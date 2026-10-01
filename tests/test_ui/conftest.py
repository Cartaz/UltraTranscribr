"""Real Qt Quick/service fixtures with isolated persistence and no inference."""

import pytest
from PySide6.QtCore import QEventLoop, QTimer, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from config.constants import AppMeta
from config.settings import Settings
from core.app_controller import AppController
from core.application_service import ApplicationService
from ui.main_window import MainWindow


@pytest.fixture
def quick_window(tmp_path, monkeypatch):
    for key in (
        "CONFIG_DIR",
        "DATA_DIR",
        "CACHE_DIR",
        "MODELS_DIR",
        "TRANSCRIPTS_DIR",
        "RECORDINGS_DIR",
        "DIARIZATION_MODELS_DIR",
    ):
        monkeypatch.setattr(AppMeta, key, tmp_path / key)
    for key in (
        "SETTINGS_PATH",
        "LOG_PATH",
        "DICTATION_METRICS_PATH",
        "DICTATION_PORTAL_STATE_PATH",
    ):
        monkeypatch.setattr(AppMeta, key, tmp_path / key)
    monkeypatch.setattr("core.app_controller.detect_gpu_backend", lambda *args: "sycl")
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    controller = AppController(Settings(preload_model=False))
    service = ApplicationService(controller)
    messages = []
    previous = qInstallMessageHandler(
        lambda kind, context, message: messages.append(message)
    )
    window = None
    try:
        window = MainWindow(service)
        window.show()
        app.processEvents()
        yield app, window, service, controller, messages
    finally:
        if window:
            window.dispose()
        service.close()
        controller.shutdown()
        app.processEvents()
        qInstallMessageHandler(previous)


def wait_until(predicate, timeout=4000):
    if predicate():
        return
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(5)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(timeout)
    loop.exec()
    poll.stop()
    deadline.stop()
    assert predicate(), "Timed out waiting for a queued Qt operation"


def visual_child(item, name):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        found = visual_child(child, name)
        if found is not None:
            return found
    return None
