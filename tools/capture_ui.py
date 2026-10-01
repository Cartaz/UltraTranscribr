"""Isolated real UI capture; the GPU detection patch belongs only to this fixture."""

import argparse, json, os, sys, tempfile
from pathlib import Path
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--frontend", choices=["qml", "web"], default="qml")
parser.add_argument(
    "--source-root", type=Path, default=Path(__file__).resolve().parents[1]
)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--populated", action="store_true")
args = parser.parse_args()
sys.path.insert(0, str(args.source_root.resolve()))
isolated = Path(tempfile.mkdtemp(prefix="ut-capture-"))
for key in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
    os.environ[key] = str(isolated / key)
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-dev-shm-usage"
)
from PySide6.QtCore import QEventLoop, QTimer, QObject, QPointF
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication
from config.settings import Settings
from core.app_controller import AppController
from core.application_service import ApplicationService
from ui.main_window import MainWindow

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
with patch("core.app_controller.detect_gpu_backend", return_value="sycl"):
    controller = AppController(Settings(preload_model=False))
service = ApplicationService(controller)
window = MainWindow(service)
window.resize(1200, 800)
window.show()


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


wait(1600)
args.output.mkdir(parents=True, exist_ok=True)
suffix = "1200x800" + (
    "-dpr2" if float(os.environ.get("QT_SCALE_FACTOR", "1")) == 2 else ""
)
try:
    for page in (
        "live",
        "file",
        "meeting",
        "history",
        "settings",
        "logs",
        "settings-advanced",
    ):
        if args.frontend == "web":
            window._web_page.runJavaScript(
                f"switchView({json.dumps(page)})"
                if page != "settings-advanced"
                else 'switchView("settings"); switchSettingsTab("advanced")'
            )
        else:
            window._window.setProperty(
                "view", "settings" if page == "settings-advanced" else page
            )
            if page == "settings-advanced":
                window._window.findChild(QObject, "settingsPage").setProperty(
                    "advanced", True
                )
        wait(600)
        if args.frontend == "web":
            window._web_view.grab().save(str(args.output / f"{page}-{suffix}.png"))
            result = []
            window._web_page.runJavaScript(
                'JSON.stringify([...document.querySelectorAll(".sidebar,.topbar,.view.active .card,.view.active input,.view.active select,.view.active .button,.view.active .metrics")].filter(e=>e.getBoundingClientRect().height).map(e=>({id:e.id,cls:e.className,text:e.textContent.trim().slice(0,60),rect:e.getBoundingClientRect().toJSON()})))',
                lambda r: result.append(r),
            )
            wait(100)
            if result:
                (args.output / f"{page}-{suffix}-geometry.json").write_text(
                    result[0] or "[]"
                )
        else:
            window._window.grabWindow().save(str(args.output / f"{page}-{suffix}.png"))
            geom = {}
            for item in window._window.findChildren(QQuickItem):
                if item.objectName() and item.isVisible():
                    pt = item.mapToScene(QPointF(0, 0))
                    geom[item.objectName()] = dict(
                        x=pt.x(), y=pt.y(), width=item.width(), height=item.height()
                    )
            (args.output / f"{page}-{suffix}-geometry.json").write_text(
                json.dumps(geom, indent=2)
            )
finally:
    window._prepare_shutdown()
    window.close()
    if hasattr(window, "dispose"):
        window.dispose()
    service.close()
    controller.shutdown()
print("Captured", args.frontend, args.output)
