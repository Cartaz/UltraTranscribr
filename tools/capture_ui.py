"""Isolated real UI capture; the GPU detection patch belongs only to this fixture."""

import argparse
import json
import os
import sys
import tempfile
import time
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
os.environ["TZ"] = "UTC"
time.tzset()
from PySide6.QtCore import QEventLoop, QLocale, QObject, QPointF, QTimer
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication

from config.settings import Settings
from core.app_controller import AppController
from core.application_service import ApplicationService
from ui.main_window import MainWindow

app = QApplication([])
QLocale.setDefault(QLocale("en_US"))
app.setQuitOnLastWindowClosed(False)
# Keep the visible fixture date identical across frontends and capture runs.
fixture_clock = patch(
    "core.transcript_history._utc_now", return_value="2026-10-01T07:00:00+00:00"
)
fixture_clock.start()
with patch("core.app_controller.detect_gpu_backend", return_value="sycl"):
    controller = AppController(Settings(preload_model=False))
service = ApplicationService(controller)
history_id = meeting_id = None
if args.populated:
    history_id = controller.history.create_session(
        kind="file",
        model="large-v3",
        language="it",
        source_path="intervista.wav",
        status="completed",
    )
    controller.history.set_name(history_id, "Intervista di prova")
    controller.history.append_text(
        history_id,
        "Una trascrizione di prova. Il testo originale resta disponibile nella cronologia.\nVerifica delle correzioni e dell’esportazione locale.",
    )
    controller.history.save_derived_output(
        history_id, "clean", "Una trascrizione di prova corretta."
    )
    store = controller.meeting.store
    meeting_id = store.create(
        model="large-v3",
        language="it",
        source="file",
        source_path="riunione.wav",
        acquisition_mode="file",
        num_speakers=2,
    )
    controller.history.set_name(meeting_id, "Riunione di prova")
    controller.history.append_text(
        meeting_id,
        "Testo originale della riunione. Verifica dei due interlocutori e delle correzioni.",
    )
    store.set_diarization(
        meeting_id,
        diarization_segments=[],
        review_segments=[
            {
                "start": i * 2.0,
                "end": i * 2.0 + 1.8,
                "speaker_id": f"SPEAKER_0{i % 2}",
                "text": f"Segmento {i + 1}: verifica della trascrizione e della revisione.",
            }
            for i in range(150)
        ],
        num_speakers=2,
    )
    store.set_speaker_name(meeting_id, "SPEAKER_00", "Francesco")
    store.set_speaker_name(meeting_id, "SPEAKER_01", "Maria")
    store.set_status(meeting_id, "completed", terminal=True)
window = MainWindow(service)
window.resize(1200, 800)
window.show()


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


wait(1600)
if args.populated:
    from core.event_bus import EventBus

    for i in range(2):
        EventBus().emit(
            "live_session_created",
            {
                "id": f"fixture-{i}",
                "source": "microphone" if i == 0 else "system",
                "source_path": "Microfono prova" if i == 0 else "Uscita predefinita",
                "model": "large-v3",
                "language": "it",
                "status": "completed",
                "terminal": True,
                "text": "Testo della sessione di prova.",
                "buffer_level": 0,
                "queue_wait_ms": 12,
                "queue_peak_ms": 24,
                "record_audio": False,
            },
        )
    if args.frontend == "web":
        window._web_page.runJavaScript(
            f"fileHistoryLoadSession({json.dumps(history_id)}); meetingLoad({json.dumps(meeting_id)});"
        )
    else:
        window.runtime.archive.select(history_id)
        window.runtime.meeting.select(meeting_id)
    wait(800)
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
        *(("meeting-review",) if args.populated else ()),
    ):
        if args.frontend == "web":
            window._web_page.runJavaScript(
                f"switchView({json.dumps('meeting' if page == 'meeting-review' else page)})"
                if page != "settings-advanced"
                else 'switchView("settings"); switchSettingsTab("advanced")'
            )
        else:
            window._window.setProperty(
                "view",
                "settings"
                if page == "settings-advanced"
                else "meeting"
                if page == "meeting-review"
                else page,
            )
            if page == "settings-advanced":
                window._window.findChild(QObject, "settingsPage").setProperty(
                    "advanced", True
                )
        wait(600)
        if page == "meeting-review":
            if args.frontend == "web":
                window._web_page.runJavaScript(
                    "document.querySelector('[data-panel=meeting]').scrollTop=850"
                )
            else:
                flick = window._window.findChild(QObject, "meetingPage").property(
                    "contentItem"
                )
                flick.setProperty(
                    "contentY",
                    min(
                        660,
                        max(
                            0,
                            flick.property("contentHeight") - flick.property("height"),
                        ),
                    ),
                )
            wait(200)
        if args.frontend == "web":
            window._web_view.grab().save(str(args.output / f"{page}-{suffix}.png"))
            result = []
            window._web_page.runJavaScript(
                'JSON.stringify([...document.querySelectorAll(".sidebar,.topbar,.view.active .card,.view.active input,.view.active select,.view.active .button,.view.active .metrics")].filter(e=>e.getBoundingClientRect().height).map(e=>({id:e.id,cls:e.className,text:e.textContent.trim().slice(0,60),rect:e.getBoundingClientRect().toJSON()})))',
                lambda r, target=result: target.append(r),
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
                    geom[item.objectName()] = {
                        "x": pt.x(),
                        "y": pt.y(),
                        "width": item.width(),
                        "height": item.height(),
                    }
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
    fixture_clock.stop()
print("Captured", args.frontend, args.output)
