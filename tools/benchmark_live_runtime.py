"""Measure real Live drain throughput and power state without exposing transcript text."""

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path


def power_state():
    online = {
        p.parent.name: p.read_text().strip()
        for p in Path("/sys/class/power_supply").glob("*/online")
    }
    return {
        "online": online,
        "connected": any(value == "1" for value in online.values()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--model-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--require-ac", action="store_true")
    args = parser.parse_args()
    if args.duration < 5:
        parser.error("La durata deve essere almeno 5 secondi")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    for kind in ("CONFIG", "DATA", "CACHE"):
        os.environ[f"XDG_{kind}_HOME"] = str(args.output / kind.lower())
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import socket

    import soundfile as sf

    from config.constants import AppMeta
    from config.settings import Settings
    from core.app_controller import AppController
    from core.audio_resampler import resample
    from core.buffer_manager import BufferManager
    from core.transcriber import TranscriberThread

    AppMeta.MODELS_DIR.parent.mkdir(parents=True)
    AppMeta.MODELS_DIR.symlink_to(args.model_cache.resolve(), target_is_directory=True)
    with sf.SoundFile(args.audio) as incoming:
        samples = incoming.read(args.duration * incoming.samplerate, dtype="float32")
        rate = incoming.samplerate
    if len(samples) < rate * 5:
        raise ValueError("Audio troppo breve")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    samples = resample(samples, rate, 16000)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    settings = Settings(language=args.language, server_port=port, preload_model=False)
    controller = AppController(settings)
    results = []

    def measure(name, operation, audio_s):
        for attempt in range(1, 4):
            checks = [power_state()]
            if args.require_ac and not checks[0]["connected"]:
                raise RuntimeError("Alimentatore non rilevato prima della prova")
            stop = threading.Event()

            def monitor():
                while not stop.wait(0.2):
                    checks.append(power_state())

            thread = threading.Thread(target=monitor)
            thread.start()
            before = time.monotonic()
            try:
                details = operation()
            finally:
                elapsed = time.monotonic() - before
                stop.set()
                thread.join()
                checks.append(power_state())
            row = {
                "name": name,
                "attempt": attempt,
                "audio_s": audio_s,
                "elapsed_s": round(elapsed, 2),
                "ac_stable": all(check["connected"] for check in checks),
                "power_samples": len(checks),
                "power_start": checks[0],
                "power_end": checks[-1],
                **details,
            }
            results.append(row)
            (args.output / "result.json").write_text(json.dumps(results, indent=2))
            print(json.dumps(row), flush=True)
            if not args.require_ac or row["ac_stable"]:
                return
        raise RuntimeError("Tre prove con alimentazione instabile: risultati esclusi")

    try:
        controller.ensure_backend_started()
        for index in range(3):

            def request():
                text = controller.backend.transcribe_audio(
                    TranscriberThread._numpy_to_wav(samples[:80000]),
                    language=args.language,
                )
                return {"has_text": bool(text)}

            measure(f"5s-request-{index + 1}", request, 5)
        for adaptive in (False, True):

            def drain():
                events = []
                buffer = BufferManager(max_memory_chunks=2)
                for offset in range(0, len(samples), settings.chunk_samples):
                    buffer.put(samples[offset : offset + settings.chunk_samples])
                buffer.close_input()
                worker = TranscriberThread(
                    buffer,
                    controller.backend,
                    settings,
                    session_id="benchmark-catchup",
                    event_sink=lambda name, _value: events.append(name),
                )
                if not adaptive:
                    worker._catchup_samples = worker._segment_samples
                try:
                    worker.run()
                    return {
                        "drained": "transcriber_drained" in events,
                        "pending_s": buffer.pending_seconds,
                        "text_chunks": events.count("transcriber_new_text"),
                    }
                finally:
                    buffer.close()

            measure(f"catchup-{adaptive}", drain, len(samples) / 16000)
    finally:
        controller.shutdown()
        (args.output / "result.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
