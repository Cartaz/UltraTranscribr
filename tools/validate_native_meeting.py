"""Validate real Whisper/SYCL + Community-1/XPU on an isolated audio excerpt.

Requires a working whisper-server in this checkout's runtime and cached models.
Outputs can contain private transcripts: keep the output directory local.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--model-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--duration", type=float, default=600)
    parser.add_argument("--timeout", type=float, default=5400)
    parser.add_argument("--memory-limit", type=int, default=8_500_000_000)
    args = parser.parse_args()
    if args.start < 0 or args.duration < 30:
        parser.error("Use a nonnegative start and at least 30 seconds of audio")
    args.audio = args.audio.resolve(strict=True)
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    for kind in ("CONFIG", "CACHE", "DATA"):
        os.environ[f"XDG_{kind}_HOME"] = str(args.output / kind.lower())
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import psutil
    import soundfile as sf

    from config.constants import AppMeta
    from config.settings import Settings
    from core.app_controller import AppController

    def digest(path):
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    original_hash = digest(args.audio)
    model_root = AppMeta.MODELS_DIR.parent
    AppMeta.MODELS_DIR.mkdir(parents=True)
    for name in ("ggml-large-v3.bin", "ggml-silero-v6.2.0.bin"):
        source = (args.model_cache / "gguf" / name).resolve(strict=True)
        (AppMeta.MODELS_DIR / name).symlink_to(source)
        sha = source.with_name(source.name + ".sha256")
        if sha.is_file():
            shutil.copy2(sha, AppMeta.MODELS_DIR / sha.name)
    shutil.copytree(
        args.model_cache / "diarization" / "community-1",
        model_root / "diarization" / "community-1",
    )
    with sf.SoundFile(args.audio) as source:
        source.seek(round(args.start * source.samplerate))
        waveform = source.read(
            round(args.duration * source.samplerate), dtype="float32"
        )
        sample_rate = source.samplerate
    excerpt = args.output / "input.wav"
    sf.write(excerpt, waveform, sample_rate, subtype="PCM_16")
    duration = len(waveform) / sample_rate
    if duration < args.duration - 0.1:
        raise ValueError("The selected excerpt extends beyond the source recording")
    del waveform
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    settings = Settings(
        model_size="large-v3",
        language="it",
        server_port=port,
        preload_model=False,
        vad_filter=True,
        backend_instances=1,
    )
    controller = None
    started = time.monotonic()
    samples = []
    result = {
        "success": False,
        "duration_s": duration,
        "start_s": args.start,
        "gpu_detection_mocked": False,
        "vad": True,
    }
    process = psutil.Process()
    try:
        controller = AppController(settings)
        session = controller.meeting.start_file(excerpt, language="it", num_speakers=0)
        result["session_id"] = session["id"]
        previous = None
        while True:
            state = controller.meeting.snapshot()
            pss, threads = 0, 0
            for child in [process, *process.children(recursive=True)]:
                try:
                    pss += child.memory_full_info().pss
                    threads += child.num_threads()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            sample = {
                "elapsed_s": round(time.monotonic() - started, 2),
                "status": state["status"],
                "progress": state["progress"],
                "diarization_progress": state["diarization_progress"],
                "pss": pss,
                "threads": threads,
            }
            samples.append(sample)
            (args.output / "progress.json").write_text(json.dumps(sample))
            signature = (
                state["status"],
                state["progress"],
                state["diarization_progress"],
            )
            if signature != previous:
                print(json.dumps(sample), flush=True)
                previous = signature
            if state["status"] in {"completed", "error", "cancelled", "interrupted"}:
                if state["status"] != "completed":
                    raise RuntimeError(state["error"] or state["status"])
                break
            if (
                pss > args.memory_limit
                or psutil.virtual_memory().available < 1_200_000_000
            ):
                raise RuntimeError(
                    "Validation stopped before exhausting desktop memory"
                )
            if time.monotonic() - started > args.timeout:
                raise TimeoutError("Native meeting validation exceeded its deadline")
            time.sleep(2)
        stored = controller.meeting.store.get(session["id"])
        source_segments = stored.get("segments") or []
        metadata = stored["meeting"]
        review = metadata["review_segments"]

        def compact(rows):
            return "".join("".join(row["text"].split()) for row in rows)

        if (
            not source_segments
            or not review
            or compact(source_segments) != compact(review)
        ):
            raise AssertionError("Review did not preserve the recognized source text")
        turns = metadata["diarization_segments"]
        if not turns:
            raise AssertionError("Community-1 returned no acoustic turns")
        result.update(
            success=True,
            source_segments=len(source_segments),
            review_rows=len(review),
            exclusive_turns=len(turns),
            regular_turns=len(metadata["speaker_diarization_segments"]),
            speakers=len({turn["speaker_id"] for turn in turns}),
            unknown_rows=sum(not row.get("speaker_id") for row in review),
            quality_issues=len(stored.get("quality_issues") or []),
            lexical_content_preserved=True,
        )
    except Exception as exc:
        result.update(error=str(exc), exception=type(exc).__name__)
        raise
    finally:
        if controller:
            controller.shutdown()
        result.update(
            elapsed_s=round(time.monotonic() - started, 2),
            peak_pss=max((sample["pss"] for sample in samples), default=0),
            originals_unchanged=digest(args.audio) == original_hash,
            remaining_python_threads=[
                t.name
                for t in threading.enumerate()
                if t is not threading.main_thread()
            ],
        )
        (args.output / "result.json").write_text(json.dumps(result, indent=2))
        (args.output / "telemetry.json").write_text(json.dumps(samples, indent=2))
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
