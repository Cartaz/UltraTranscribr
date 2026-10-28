"""Cancellable process ownership for the optional English meeting workflow."""

from __future__ import annotations

import json
import logging
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
from contextlib import nullcontext
from pathlib import Path

from config.constants import AppMeta
from core.english_models import EnglishModelManager, EnglishPipelineCancelled
from core.meeting_engine import meeting_language

logger = logging.getLogger(__name__)
STAGES = (
    ("prepare", 5, "Verifica dei modelli"),
    ("asr", 50, "Trascrizione della riunione · Qwen"),
    ("ctc", 12, "Allineamento delle parole · 1 di 2"),
    ("qwen", 15, "Allineamento delle parole · 2 di 2"),
    ("combine", 1, "Preparazione della revisione"),
    ("diar", 17, "Riconoscimento degli interlocutori"),
)


class EnglishMeetingThread(threading.Thread):
    def __init__(
        self,
        source: str | Path,
        *,
        models: EnglishModelManager | None = None,
        diarization_models: Path | None = None,
        num_speakers: int = 0,
        language: str = "en",
        diarization_only: bool = False,
        artifact_dir: Path | None = None,
        prepare_models_only: bool = False,
        event_sink=None,
        thread_name="EnglishMeeting",
    ):
        super().__init__(name=thread_name, daemon=True)
        self.source = Path(source).resolve()
        self.models = models or EnglishModelManager()
        self.diarization_models = (
            diarization_models or self.models.path("community3").parent
        )
        self.num_speakers = num_speakers
        self.language = meeting_language(language)
        self.diarization_only = diarization_only
        self.artifact_dir = artifact_dir
        self.prepare_models_only = prepare_models_only
        self.event_sink = event_sink or (lambda *_: None)
        self._stop_event = threading.Event()
        self._child_lock = threading.RLock()
        self._child = None
        self._terminal_state = None
        self.provenance = {}
        self.exclusive_segments = []
        self.speaker_segments = []

    def _emit(self, name, payload):
        if not self._stop_event.is_set():
            self.event_sink(name, payload)

    def stop(self):
        self._stop_event.set()
        self._terminate_child()

    def _terminate_child(self):
        with self._child_lock:
            process = self._child
            if process is None or process.poll() is not None:
                return
            try:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)
            except ProcessLookupError:
                pass

    def _stage_command(self, stage: str, work: Path) -> list[str]:
        return [
            sys.executable,
            "-m",
            "core.english_worker",
            "--stage",
            stage,
            "--source",
            str(self.source),
            "--work",
            str(work),
            "--models",
            str(self.models.root),
            "--diarization-models",
            str(self.diarization_models),
            "--speakers",
            str(self.num_speakers),
            "--language",
            self.language,
        ]

    @staticmethod
    def _check_memory():
        info = Path("/proc/meminfo")
        if info.exists():
            available = next(
                (
                    int(line.split()[1]) * 1024
                    for line in info.read_text().splitlines()
                    if line.startswith("MemAvailable:")
                ),
                None,
            )
            if available is not None and available < 1_200_000_000:
                raise RuntimeError(
                    "Memoria disponibile insufficiente per completare la riunione."
                )

    def _run_stage(self, stage, work, base_progress, weight):
        if self._stop_event.is_set():
            raise EnglishPipelineCancelled()
        error_path = work / f"{stage}.log"
        with error_path.open("wb") as errors:
            with self._child_lock:
                if self._stop_event.is_set():
                    raise EnglishPipelineCancelled()
                process = subprocess.Popen(
                    self._stage_command(stage, work),
                    stdout=subprocess.PIPE,
                    stderr=errors,
                    cwd=Path(__file__).resolve().parents[1],
                    start_new_session=True,
                    env=os.environ | {"OMP_NUM_THREADS": "2", "HF_HUB_OFFLINE": "1"},
                )
                self._child = process
            buffer = b""
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while selector.get_map():
                        if self._stop_event.is_set():
                            raise EnglishPipelineCancelled()
                        self._check_memory()
                        for key, _ in selector.select(timeout=0.2):
                            data = os.read(key.fd, 65536)
                            if not data:
                                selector.unregister(key.fileobj)
                                continue
                            buffer += data
                            if len(buffer) > 1_000_000:
                                raise RuntimeError(
                                    "Risposta del processo riunioni troppo grande."
                                )
                            while b"\n" in buffer:
                                line, buffer = buffer.split(b"\n", 1)
                                try:
                                    value = json.loads(line)
                                except (ValueError, UnicodeDecodeError):
                                    continue
                                if isinstance(value, dict) and isinstance(
                                    value.get("progress"), int
                                ):
                                    percent = max(0, min(100, value["progress"]))
                                    if stage == "diar":
                                        self._emit(
                                            "file_transcriber_diarization_progress",
                                            percent,
                                        )
                                    self._emit(
                                        "file_transcriber_progress",
                                        base_progress + int(weight * percent / 100),
                                    )
                code = process.wait()
                if self._stop_event.is_set():
                    raise EnglishPipelineCancelled()
                if code:
                    logger.error(
                        "English stage %s failed: %s",
                        stage,
                        error_path.read_text(errors="replace")[-4000:],
                    )
                    result_path = work / f"{stage}-result.json"
                    result = (
                        json.loads(result_path.read_text())
                        if result_path.exists()
                        else {}
                    )
                    raise RuntimeError(
                        result.get("error") or "Elaborazione della riunione interrotta."
                    )
            finally:
                self._terminate_child()
                if process.stdout:
                    process.stdout.close()
                with self._child_lock:
                    self._child = None

    def run(self):
        try:
            self._emit("file_transcriber_status_changed", "running")
            self._emit("file_transcriber_progress", 0)
            cache = AppMeta.CACHE_DIR / "english-jobs"
            cache.mkdir(parents=True, exist_ok=True)
            if self.artifact_dir is not None:
                self.artifact_dir.mkdir(parents=True, exist_ok=False)
            workspace = (
                nullcontext(self.artifact_dir)
                if self.artifact_dir is not None
                else tempfile.TemporaryDirectory(prefix="meeting-", dir=cache)
            )
            with workspace as temporary:
                work = Path(temporary)
                completed = 0
                stages = (
                    (
                        ("prepare_diar", 10, "Preparazione audio"),
                        ("diar", 90, "Riconoscimento degli interlocutori"),
                    )
                    if self.diarization_only
                    else STAGES
                )
                if self.prepare_models_only:
                    stages = (("download", 100, "Preparazione dei modelli riunioni"),)
                elif not self.diarization_only and self.language != "en":
                    stages = tuple(
                        (name, weight + (12 if name == "qwen" else 0),
                         "Allineamento delle parole" if name == "qwen" else label)
                        for name, weight, label in stages if name != "ctc"
                    )
                for stage, weight, label in stages:
                    self._emit("file_transcriber_detail", label)
                    self._run_stage(stage, work, completed, weight)
                    completed += weight
                if self._stop_event.is_set():
                    raise EnglishPipelineCancelled()
                if self.prepare_models_only:
                    self._terminal_state = "completed"
                    self._emit("file_transcriber_progress", 100)
                    self._emit("file_transcriber_completed", None)
                    return
                result = (
                    {
                        "segments": [],
                        "quality": [],
                        "provenance": json.loads(
                            (work / "provenance.json").read_text()
                        ),
                        "source_audit": {"operation": "diarization_only"},
                    }
                    if self.diarization_only
                    else json.loads((work / "final.json").read_text())
                )
                diarization = json.loads((work / "diarization.json").read_text())
                self.exclusive_segments = diarization["exclusive"]
                self.speaker_segments = diarization["regular"]
                self.provenance = result["provenance"] | {
                    "source_audit": result["source_audit"],
                    "diarization": diarization["configuration"]
                    | {"models": diarization.get("model_hashes", {})},
                }
                self.provenance["stages"] = {
                    stage: json.loads((work / f"{stage}-result.json").read_text())
                    for stage, _, _ in stages
                    if (work / f"{stage}-result.json").exists()
                }
                if not self.diarization_only:
                    self._emit(
                        "file_transcriber_new_text",
                        "\n".join(row["text"] for row in result["segments"]),
                    )
                    self._emit("file_transcriber_segments", result["segments"])
                if result["quality"]:
                    self._emit("file_transcriber_quality", result["quality"])
                self._terminal_state = "completed"
                self._emit("file_transcriber_progress", 100)
                self._emit("file_transcriber_status_changed", "completed")
                self._emit("file_transcriber_completed", None)
        except EnglishPipelineCancelled:
            self._terminal_state = "stopped"
        except Exception as exc:
            self._terminal_state = "error"
            logger.exception("English meeting pipeline failed")
            self._emit("file_transcriber_error", str(exc))
            self._emit("file_transcriber_status_changed", "error")
        finally:
            self._terminate_child()
