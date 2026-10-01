"""Launch the actual composition root in isolation; no GPU inference is claimed."""

import argparse
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
isolated = Path(tempfile.mkdtemp(prefix="ut-main-smoke-"))
for key in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
    os.environ[key] = str(isolated / key)
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import main
from config.settings import Settings

Settings(preload_model=False).save()
result = {"gpu_detection_fixture": True, "inference_exercised": False, "views": []}


def create_app(argv):
    app = QApplication(argv)

    def exercise():
        for window in app.topLevelWindows():
            if window.objectName() == "mainWindow":
                page = ("live", "file", "meeting", "history", "settings", "logs")[
                    len(result["views"])
                ]
                window.setProperty("view", page)
                result["views"].append(page)
                if len(result["views"]) < 6:
                    QTimer.singleShot(300, exercise)
                    return
                args.output.parent.mkdir(parents=True, exist_ok=True)
                window.grabWindow().save(str(args.output.with_suffix(".png")))
        rollup = Path("/proc/self/smaps_rollup").read_text()
        result["memory_kib"] = {
            line.split(":")[0]: int(line.split()[1])
            for line in rollup.splitlines()
            if line.startswith(("Pss:", "Rss:", "Private_Clean:", "Private_Dirty:"))
        }
        result["webengine_modules"] = [
            name
            for name in sys.modules
            if "QtWebEngine" in name or "QtWebChannel" in name
        ]
        app.quit()

    QTimer.singleShot(1000, exercise)
    QTimer.singleShot(10000, app.quit)
    return app


with (
    patch("core.app_controller.detect_gpu_backend", return_value="sycl"),
    patch.object(main, "QApplication", side_effect=create_app),
):
    try:
        main.main()
    except SystemExit as exc:
        result["exit_code"] = exc.code
result["remaining_threads"] = [
    t.name for t in threading.enumerate() if t is not threading.main_thread()
]
args.output.write_text(json.dumps(result, indent=2))
print(json.dumps(result))
if (
    result.get("exit_code") != 0
    or len(result["views"]) != 6
    or result["webengine_modules"]
):
    raise SystemExit(1)
