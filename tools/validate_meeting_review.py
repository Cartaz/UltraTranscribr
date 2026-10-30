"""Exercise a real long meeting in an isolated native desktop application.

Inputs are read only. The history, metadata and FLAC are copied into a fresh
XDG data directory. Screenshots/transcripts can contain private meeting data:
keep the output local. This tool never starts inference or recording.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--meeting", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--source-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--frontend", choices=["qml", "web"], default="qml")
    parser.add_argument("--cycles", type=int, default=12)
    parser.add_argument("--checkpoint-only", action="store_true")
    parser.add_argument("--reopen", action="store_true")
    parser.add_argument(
        "--skip-playback",
        action="store_true",
        help="Isolate the editor workload for frontend memory comparisons",
    )
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.source_root.resolve()))
    for kind in ("CONFIG", "CACHE", "DATA"):
        os.environ[f"XDG_{kind}_HOME"] = str(args.output / kind.lower())

    import psutil
    from PySide6.QtCore import (
        QCoreApplication,
        QEvent,
        QEventLoop,
        QObject,
        QPoint,
        Qt,
        QTimer,
    )
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from config.constants import AppMeta
    from config.settings import Settings
    from core.app_controller import AppController
    from core.application_service import ApplicationService
    from ui.main_window import MainWindow

    def digest(path):
        with Path(path).open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()

    hashes = {
        str(path): digest(path) for path in (args.history, args.meeting, args.audio)
    }
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    controller = AppController(Settings(language="it", preload_model=False))
    service = ApplicationService(controller)
    history = json.loads(args.history.read_text())
    metadata = json.loads(args.meeting.read_text())
    sid = history["id"]
    if not args.reopen:
        controller.history.root.mkdir(parents=True, exist_ok=True)
        controller.meeting.store.root.mkdir(parents=True, exist_ok=True)
        AppMeta.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        target_audio = AppMeta.RECORDINGS_DIR / f"{sid}.flac"
        shutil.copyfile(args.audio, target_audio)
        metadata["recording"]["path"] = str(target_audio)
        (controller.history.root / f"{sid}.json").write_text(
            json.dumps(history, ensure_ascii=False)
        )
        (controller.meeting.store.root / f"{sid}.json").write_text(
            json.dumps(metadata, ensure_ascii=False)
        )
        original = (metadata.get("original_recording") or {}).get("path")
        if original and Path(original).is_file():
            hashes[str(original)] = digest(original)
            controller.meeting.store.retain_original(sid, Path(original))
    process = psutil.Process()
    result = {
        "frontend": args.frontend,
        "native_desktop": True,
        "gpu_detection_mocked": False,
        "inference_exercised": False,
        "input_rows": len(metadata["review_segments"]),
        "cycles": [],
        "input_hashes": hashes,
        "pid": process.pid,
    }
    (args.output / "pid").write_text(str(process.pid))
    window = MainWindow(service)
    telemetry_stop = threading.Event()
    telemetry_fault = []
    memory_samples = []

    def wait_until(predicate, timeout=15000):
        deadline = time.monotonic() + timeout / 1000
        while not predicate():
            if telemetry_fault:
                raise RuntimeError(telemetry_fault[0])
            if time.monotonic() > deadline:
                raise TimeoutError("Native UI operation timed out")
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()

    def settle(ms=150):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()
        if telemetry_fault:
            raise RuntimeError(telemetry_fault[0])

    def sample(label):
        children = process.children(recursive=True)
        records = []
        for item in [process, *children]:
            try:
                info = item.memory_full_info()
                records.append(
                    {
                        "pid": item.pid,
                        "name": item.name(),
                        "rss": info.rss,
                        "pss": getattr(info, "pss", 0),
                        "uss": getattr(info, "uss", 0),
                        "threads": item.num_threads(),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        value = {
            "label": label,
            "processes": records,
            "rss": sum(r["rss"] for r in records),
            "pss": sum(r["pss"] for r in records),
            "threads": sum(r["threads"] for r in records),
            "time": time.monotonic(),
        }
        # Abort before an experimental regression can exhaust the desktop.
        if value["pss"] > 1_800_000_000:
            raise RuntimeError(
                "Review process group exceeded the validation memory guard"
            )
        return value

    def record_memory():
        while not telemetry_stop.wait(0.2):
            try:
                memory_samples.append(sample("telemetry"))
            except (RuntimeError, OSError, psutil.Error) as exc:
                telemetry_fault.append(str(exc))
                return

    telemetry = threading.Thread(
        target=record_memory, name="AuditTelemetry", daemon=True
    )
    telemetry.start()

    def js(code):
        box = []
        window._web_page.runJavaScript(code, lambda value: box.append(value))
        wait_until(lambda: bool(box))
        return box[0]

    def load():
        if args.frontend == "qml":
            window.runtime.meeting.select(sid)
            wait_until(
                lambda: window.runtime.meeting.segments.count == result["input_rows"]
            )
        else:
            js(f"meetingLoad({json.dumps(sid)}); true")
            wait_until(
                lambda: js(
                    "!!meetingCurrent && meetingCurrent.id === " + json.dumps(sid)
                )
            )
            wait_until(
                lambda: (
                    js(
                        "document.querySelectorAll('#meeting-review-list textarea').length"
                    )
                    == result["input_rows"]
                )
            )

    def qml_item(name):
        return window._window.findChild(QObject, name)

    try:
        window.resize(1200, 800)
        window.show()
        settle(1200)
        if args.frontend == "qml":
            window._window.setProperty("view", "meeting")
        else:
            js("switchView('meeting');true")
        result["empty"] = sample("empty")
        load()
        settle(300)
        if args.frontend == "qml":
            page = qml_item("meetingPage").property("contentItem")
            page.setProperty("contentY", 850)
            settle()
            player = qml_item("audioMediaPlayer")
            output = qml_item("audioOutput")
            assert isinstance(player, QMediaPlayer) and isinstance(output, QAudioOutput)
            output.setMuted(True)
            if not args.skip_playback:
                wait_until(lambda: player.duration() > 0)
                player.setPosition(120000)
                player.play()
                wait_until(lambda: player.position() > 120300)
                player.pause()
            result["playback"] = {
                "duration_ms": player.duration(),
                "position_ms": player.position(),
                "muted": output.isMuted(),
                "actual_decoder": player.duration() > 0,
                "playback_exercised": not args.skip_playback,
            }
            window._window.grabWindow().save(str(args.output / "long-review.png"))
        else:
            if not args.skip_playback:
                wait_until(
                    lambda: (
                        js("document.getElementById('meeting-audio').readyState") >= 1
                    )
                )
                js(
                    "var a=document.getElementById('meeting-audio');a.muted=true;a.currentTime=120;a.scrollIntoView({block:'center'});true"
                )
                rect = js(
                    "JSON.stringify((()=>{var r=document.getElementById('meeting-audio').getBoundingClientRect();return {x:r.left,y:r.top}})())"
                )
                rect = json.loads(rect)
                window._web_view.setFocus()
                QTest.mouseClick(
                    window._web_view.focusProxy() or window._web_view,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                    QPoint(int(rect["x"] + 20), int(rect["y"] + 20)),
                )
                wait_until(
                    lambda: (
                        js("document.getElementById('meeting-audio').currentTime")
                        > 120.3
                    )
                )
                js("document.getElementById('meeting-audio').pause();true")
            result["playback"] = {"playback_exercised": not args.skip_playback}
            window.grab().save(str(args.output / "long-review.png"))
        if args.checkpoint_only or args.reopen:
            assert args.frontend == "qml"
            meeting = window.runtime.meeting
            if args.reopen:
                assert (
                    meeting.segments.get(0)["draft_text"]
                    == "Bozza sopravvissuta al crash"
                )
                result["crash_draft_restored"] = True
            else:
                meeting.editText(0, "Bozza sopravvissuta al crash")
                wait_until(
                    lambda: not meeting._draft_pending and not meeting._draft_writing
                )
                (args.output / "checkpoint-ready").write_text("durable")
                # Parent validation deliberately kills this process at this
                # acknowledged checkpoint, without orderly window disposal.
                while True:
                    settle(100)
        else:
            for cycle in range(args.cycles):
                index = 0 if cycle % 2 == 0 else result["input_rows"] - 1
                text = f"Verifica di salvataggio {cycle}"
                if args.frontend == "qml":
                    meeting = window.runtime.meeting
                    listing = qml_item("meetingReviewList")
                    listing.positionViewAtIndex(index, 0)
                    settle(50)
                    meeting.editText(index, text)
                    meeting.saveAll()
                    wait_until(
                        lambda meeting=meeting: (
                            not meeting.saving
                            and not meeting.dirty
                            and not meeting._draft_pending
                            and not meeting._draft_writing
                        )
                    )
                else:
                    js(
                        f"var t=document.querySelectorAll('#meeting-review-list textarea')[{index}];t.value={json.dumps(text)};t.dispatchEvent(new Event('input',{{bubbles:true}}));meetingSaveAllReviewEdits();true"
                    )
                    wait_until(
                        lambda: js(
                            "!meetingReviewSaving && meetingReviewDirty.size===0"
                        )
                    )
                assert (
                    controller.meeting.store.get(sid)["meeting"]["review_segments"][
                        index
                    ]["text"]
                    == text
                )
                load()
                settle(150)
                result["cycles"].append(sample(f"save-reopen-{cycle}"))
            result["all_saves_verified"] = True
        result["webengine_modules"] = [
            key for key in sys.modules if "QtWebEngine" in key or "QtWebChannel" in key
        ]
        if args.frontend == "qml":
            assert not result["webengine_modules"]
        for path, digest in hashes.items():
            with Path(path).open("rb") as handle:
                assert hashlib.file_digest(handle, "sha256").hexdigest() == digest
        result["originals_unchanged"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if args.frontend == "qml":
            window.dispose()
        else:
            window._prepare_shutdown()
            window._web_view.deleteLater()
            window.deleteLater()
        service.close()
        controller.shutdown()
        telemetry_stop.set()
        telemetry.join(timeout=2)
        result["memory_samples"] = memory_samples
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        result["remaining_python_threads"] = [
            thread.name
            for thread in threading.enumerate()
            if thread is not threading.main_thread()
        ]
        (args.output / "result.json").write_text(json.dumps(result, indent=2))
        print(
            json.dumps(
                {
                    k: v
                    for k, v in result.items()
                    if k not in {"cycles", "memory_samples", "input_hashes"}
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
