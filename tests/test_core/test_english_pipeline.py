import json
import sys
import threading
import time
from pathlib import Path

from config.constants import AppMeta
from core.english_pipeline import EnglishMeetingThread


def test_cancellation_stops_worker_and_descendants_without_publishing_text(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(AppMeta, "CACHE_DIR", tmp_path / "cache")
    marker = tmp_path / "child.pid"
    ready = threading.Event()
    events = []

    class SleepingPipeline(EnglishMeetingThread):
        def _stage_command(self, stage, work):
            script = (
                "import subprocess,sys,time,pathlib;"
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
                f"pathlib.Path({str(marker)!r}).write_text(str(p.pid));"
                "print('{\"progress\": 50}',flush=True);time.sleep(30)"
            )
            return [sys.executable, "-c", script]

    def event(name, payload):
        events.append((name, payload))
        if name == "file_transcriber_progress" and payload > 0:
            ready.set()

    pipeline = SleepingPipeline(tmp_path / "audio.wav", event_sink=event)
    pipeline.start()
    try:
        assert ready.wait(5)
        descendant = int(marker.read_text())
        started = time.monotonic()
        pipeline.stop()
        pipeline.join(timeout=5)
        assert time.monotonic() - started < 5
        assert not pipeline.is_alive()
        assert pipeline._terminal_state == "stopped"
        assert not any(name == "file_transcriber_segments" for name, _ in events)
        state = Path(f"/proc/{descendant}/stat")
        assert not state.exists() or state.read_text().split()[2] == "Z"
    finally:
        pipeline.stop()
        pipeline.join(timeout=5)


def test_failed_worker_cannot_report_a_completed_meeting(tmp_path, monkeypatch):
    monkeypatch.setattr(AppMeta, "CACHE_DIR", tmp_path / "cache")
    events = []

    class FailedPipeline(EnglishMeetingThread):
        def _stage_command(self, stage, work):
            return [sys.executable, "-c", "raise SystemExit(3)"]

    pipeline = FailedPipeline(
        tmp_path / "audio.wav", event_sink=lambda *item: events.append(item)
    )
    pipeline.start()
    pipeline.join(timeout=5)
    assert not pipeline.is_alive()
    assert pipeline._terminal_state == "error"
    assert sum(name == "file_transcriber_error" for name, _ in events) == 1
    assert not any(name == "file_transcriber_completed" for name, _ in events)
    assert pipeline._child is None


def test_ready_pipeline_publishes_only_final_aligned_text(tmp_path, monkeypatch):
    monkeypatch.setattr(AppMeta, "CACHE_DIR", tmp_path / "cache")
    events = []

    class ReadyPipeline(EnglishMeetingThread):
        def _run_stage(self, stage, work, base_progress, weight):
            if stage == "diar":
                (work / "diarization.json").write_text(
                    json.dumps(
                        {
                            "exclusive": [
                                {"start": 0, "end": 2, "speaker_id": "SPEAKER_00"}
                            ],
                            "regular": [],
                            "configuration": {"duration_s": 3},
                        }
                    )
                )
            if stage == "combine":
                result = {
                    "segments": [{"text": "One two", "start": 0, "end": 2}],
                    "quality": [],
                    "provenance": {"pipeline": "fixture"},
                    "source_audit": {"complete_audio_coverage": True},
                }
                (work / "final.json").write_text(json.dumps(result))

    pipeline = ReadyPipeline(
        tmp_path / "audio.wav", event_sink=lambda *item: events.append(item)
    )
    pipeline.start()
    pipeline.join(timeout=5)
    assert pipeline._terminal_state == "completed"
    assert [
        payload for name, payload in events if name == "file_transcriber_new_text"
    ] == ["One two"]
    assert sum(name == "file_transcriber_segments" for name, _ in events) == 1
    assert pipeline.provenance["source_audit"]["complete_audio_coverage"]


def test_voice_only_rerun_does_not_republish_or_recognize_text(tmp_path, monkeypatch):
    monkeypatch.setattr(AppMeta, "CACHE_DIR", tmp_path / "cache")
    events, stages = [], []

    class ReadyDiarization(EnglishMeetingThread):
        def _run_stage(self, stage, work, base_progress, weight):
            stages.append(stage)
            if stage == "prepare_diar":
                (work / "provenance.json").write_text(json.dumps({"fixture": True}))
            else:
                (work / "diarization.json").write_text(
                    json.dumps(
                        {
                            "exclusive": [
                                {"start": 0, "end": 2, "speaker_id": "SPEAKER_00"}
                            ],
                            "regular": [],
                            "configuration": {"duration_s": 3},
                        }
                    )
                )

    pipeline = ReadyDiarization(
        tmp_path / "audio.wav",
        diarization_only=True,
        event_sink=lambda *event: events.append(event),
    )
    pipeline.start()
    pipeline.join(timeout=5)
    assert pipeline._terminal_state == "completed"
    assert stages == ["prepare_diar", "diar"]
    assert len(pipeline.exclusive_segments) == 1
    assert not any(
        name in {"file_transcriber_new_text", "file_transcriber_segments"}
        for name, _ in events
    )


def test_model_preparation_has_no_audio_stages_or_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(AppMeta, "CACHE_DIR", tmp_path / "cache")
    stages, events = [], []

    class Prepared(EnglishMeetingThread):
        def _run_stage(self, stage, work, base_progress, weight):
            stages.append(stage)

    worker = Prepared(tmp_path / "not-an-audio-file", prepare_models_only=True,
                      event_sink=lambda *event: events.append(event))
    worker.start()
    worker.join(timeout=5)
    assert worker._terminal_state == "completed"
    assert stages == ["download"]
    assert any(name == "file_transcriber_completed" for name, _ in events)
    assert not any(name in {"file_transcriber_new_text", "file_transcriber_segments"}
                   for name, _ in events)


def test_italian_meeting_skips_english_ctc_and_preserves_language(tmp_path, monkeypatch):
    monkeypatch.setattr(AppMeta, "CACHE_DIR", tmp_path / "cache")
    stages = []

    class ItalianPipeline(EnglishMeetingThread):
        def _run_stage(self, stage, work, base_progress, weight):
            stages.append((stage, base_progress, weight))
            if stage == "combine":
                (work / "final.json").write_text(json.dumps({
                    "segments": [{"text": "Ciao a tutti", "start": 0, "end": 2}],
                    "quality": [], "provenance": {"ASR": {"language": "it"}},
                    "source_audit": {"complete_audio_coverage": True},
                }))
            if stage == "diar":
                (work / "diarization.json").write_text(json.dumps({
                    "exclusive": [], "regular": [], "configuration": {},
                }))

    worker = ItalianPipeline(tmp_path / "audio.wav", language="it-IT")
    worker.run()
    assert worker._terminal_state == "completed"
    assert [name for name, _, _ in stages] == ["prepare", "asr", "qwen", "combine", "diar"]
    assert sum(weight for _, _, weight in stages) == 100
    assert worker.provenance["ASR"]["language"] == "it"
    command = worker._stage_command("qwen", tmp_path)
    assert command[command.index("--language") + 1] == "it"


def test_unsupported_meeting_language_is_rejected_before_loading(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="lingua supportata"):
        EnglishMeetingThread(tmp_path / "audio.wav", language="auto")
