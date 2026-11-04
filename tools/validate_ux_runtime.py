"""Isolated real GPU smoke test; output audio/transcripts remain local."""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--model-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()
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
    from core.transcriber import TranscriberThread

    root = AppMeta.MODELS_DIR.parent
    root.mkdir(parents=True)
    for child in args.model_cache.iterdir():
        (root / child.name).symlink_to(
            child.resolve(), target_is_directory=child.is_dir()
        )
    source = args.output / "source.wav"
    with sf.SoundFile(args.audio) as incoming:
        samples = incoming.read(args.duration * incoming.samplerate, dtype="float32")
        rate = incoming.samplerate
    sf.write(source, samples, rate, subtype="PCM_16")
    source_bytes = source.read_bytes()
    result = {
        "mocked": False,
        "source_duration_s": len(samples) / rate,
        "power_supply": {},
    }
    for name in ("ADP1/online", "BAT0/status"):
        path = Path("/sys/class/power_supply") / name
        if path.exists():
            result["power_supply"][name] = path.read_text().strip()
    controller = None
    process = psutil.Process()
    telemetry = []
    started = time.monotonic()
    try:
        controller = AppController(
            Settings(language="en", preload_model=False, server_port=18097)
        )
        session = controller.meeting.start_file(
            str(source), language="en", num_speakers=0
        )
        previous = None
        while True:
            state = controller.meeting.snapshot()
            family = [process, *process.children(recursive=True)]
            pss = 0
            for proc in family:
                try:
                    pss += proc.memory_full_info().pss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            telemetry.append(
                {
                    "elapsed_s": round(time.monotonic() - started, 2),
                    "pss_bytes": pss,
                    "ac_online": Path("/sys/class/power_supply/ADP1/online")
                    .read_text()
                    .strip()
                    if Path("/sys/class/power_supply/ADP1/online").exists()
                    else None,
                    "status": state["status"],
                    "progress": state["progress"],
                }
            )
            signature = state["status"], state["progress"]
            if signature != previous:
                print(json.dumps(telemetry[-1]), flush=True)
                previous = signature
            if state["status"] in {"completed", "error", "cancelled", "interrupted"}:
                if state["status"] != "completed":
                    raise RuntimeError(state.get("error") or state["status"])
                break
            if time.monotonic() - started > args.timeout or pss > 9_000_000_000:
                raise RuntimeError("Limite di tempo o memoria del collaudo raggiunto")
            time.sleep(1)
        store = controller.meeting.store
        original = store.playback_path(session["id"])
        assert original.read_bytes() == source_bytes
        assert original != store.recording_path(session["id"])
        metadata = store.get(session["id"])["meeting"]
        assert metadata["review_segments"]
        store.edit_review_segment(session["id"], 0, "Correzione di collaudo")
        store.undo_review(session["id"])
        store.undo_review(session["id"], redo=True)
        assert (
            store.get(session["id"])["meeting"]["review_segments"][0]["text"]
            == "Correzione di collaudo"
        )
        store.export(session["id"], args.output / "meeting.txt", "txt")
        store.export(session["id"], args.output / "meeting.srt", "srt")
        result.update(
            meeting_success=True,
            meeting_elapsed_s=round(time.monotonic() - started, 2),
            pipeline=metadata["processing_pipeline"]["id"],
            rows=len(metadata["review_segments"]),
            source_sha256=hashlib.sha256(source_bytes).hexdigest(),
            original_byte_identical=True,
            distinct_analysis_audio=True,
            review_persistence_undo_redo=True,
        )
        # A short real SYCL request after the Qwen worker released GPU ownership.
        controller.ensure_backend_started()
        import numpy as np

        mono = samples.mean(axis=1) if samples.ndim == 2 else samples
        from core.audio_resampler import resample

        mono = resample(mono[: rate * 5], rate, 16000)
        before = time.monotonic()
        text = controller.backend.transcribe_audio(
            TranscriberThread._numpy_to_wav(np.asarray(mono)), language="en"
        )
        result["whisper_5s_elapsed_s"] = round(time.monotonic() - before, 2)
        result["whisper_returned_text"] = bool(text)
        store.delete_audio(session["id"])
        assert store.playback_path(session["id"]) is None
        assert source.read_bytes() == source_bytes
        result["managed_audio_deletion_preserves_source"] = True
        result["success"] = True
    except Exception as exc:
        result.update(success=False, error=str(exc), exception=type(exc).__name__)
        raise
    finally:
        if controller:
            controller.shutdown()
        result["power_supply_end"] = {
            name: (Path("/sys/class/power_supply") / name).read_text().strip()
            for name in ("ADP1/online", "BAT0/status")
            if (Path("/sys/class/power_supply") / name).exists()
        }
        result["elapsed_s"] = round(time.monotonic() - started, 2)
        result["peak_pss_bytes"] = max((r["pss_bytes"] for r in telemetry), default=0)
        (args.output / "result.json").write_text(json.dumps(result, indent=2))
        (args.output / "telemetry.json").write_text(json.dumps(telemetry, indent=2))
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
