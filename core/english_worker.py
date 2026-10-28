"""One isolated stage of the optional English meeting pipeline."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import subprocess
import time
import wave
from pathlib import Path
from threading import Event

from core.english_models import EnglishModelManager
from core.meeting_engine import meeting_language


def save(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    temporary.replace(path)


def load(path: Path):
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def progress(value: int) -> None:
    print(json.dumps({"progress": max(0, min(100, value))}), flush=True)


def run_stage(
    stage: str,
    source: Path,
    work: Path,
    models: EnglishModelManager,
    diarization_models: Path | None = None,
    speakers: int = 0,
    language: str = "en",
):
    language = meeting_language(language)
    audio = work / "audio.wav"
    if stage == "download":
        models.dependencies()
        models.download(cancel=Event(), progress=progress)
    elif stage in {"prepare", "prepare_diar"}:
        versions = models.dependencies() if stage == "prepare" else {}
        hashes = (
            models.verify(progress=lambda value: progress(int(value * 0.8)))
            if stage == "prepare"
            else {}
        )
        original = digest(source)
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(audio),
            ],
            check=True,
        )
        with wave.open(str(audio), "rb") as stream:
            frames = stream.getnframes()
        if frames == 0 or digest(source) != original:
            raise RuntimeError("L'audio di origine non è valido o è stato modificato.")
        save(
            work / "provenance.json",
            {
                "pipeline": ("qwen-dual-alignment-community3" if language == "en"
                             else "qwen-multilingual-alignment-community3"),
                "source_sha256": original,
                "pcm_sha256": digest(audio),
                "frames": frames,
                "sample_rate": 16000,
                "versions": versions,
                "models": hashes,
                "ASR": {"language": language, "chunk_s": 30, "overlap_s": 0, "VAD": False},
                "alignment": ({"device": "cpu", "CTC_threshold": 0.2} if language == "en"
                              else {"device": "cpu", "method": "qwen", "language": language}),
            },
        )
    elif stage == "asr":
        from config.constants import ProcessDefaults
        from config.settings import Settings
        from core.english_asr import EnglishASRBackend
        from core.file_transcriber import FileTranscriberThread

        ProcessDefaults.FILE_SEGMENT_LENGTH_S = 30
        ProcessDefaults.FILE_OVERLAP_DURATION_S = 0
        backend = EnglishASRBackend(models.path("qwen-asr"), Event())
        rows, quality, chunks, requests = [], [], [], []
        original_request = backend.transcribe_audio

        def transcribe(audio_data, **kwargs):
            response = original_request(audio_data, **kwargs)
            with wave.open(io.BytesIO(audio_data), "rb") as stream:
                pcm = stream.readframes(stream.getnframes())
            requests.append(
                {"pcm_sha256": hashlib.sha256(pcm).hexdigest(), "frames": len(pcm) // 2}
            )
            return response

        backend.transcribe_audio = transcribe

        class TracedWorker(FileTranscriberThread):
            def _request_checked_chunk(self, pcm16, prompt, offset_s):
                entry = {
                    "start_s": offset_s,
                    "end_s": offset_s + len(pcm16) / 32000,
                    "pcm_sha256": hashlib.sha256(pcm16).hexdigest(),
                    "completed": False,
                }
                chunks.append(entry)
                response = super()._request_checked_chunk(pcm16, prompt, offset_s)
                entry["completed"] = True
                return response

        def event(name, payload):
            if name == "file_transcriber_segments":
                rows.extend(payload)
            elif name == "file_transcriber_quality":
                quality.extend(payload)
            elif name == "file_transcriber_progress":
                progress(int(payload))

        try:
            backend.start()
            worker = TracedWorker(
                str(audio),
                backend,
                Settings(language=language, vad_filter=False),
                language=language,
                event_sink=event,
            )
            worker.run()
            if worker._terminal_state != "completed":
                raise RuntimeError("La trascrizione della riunione non è stata completata.")
            provenance = load(work / "provenance.json")
            if not chunks or not all(chunk["completed"] for chunk in chunks):
                raise RuntimeError("La trascrizione della riunione ha perso un blocco audio.")
            if round(chunks[-1]["end_s"] * 16000) != provenance["frames"]:
                raise RuntimeError(
                    "La trascrizione della riunione non copre la fine dell'audio."
                )
            if len(chunks) != math.ceil(provenance["frames"] / 480000) or any(
                round(chunk["start_s"] * 16000) != index * 480000
                for index, chunk in enumerate(chunks)
            ):
                raise RuntimeError("La trascrizione della riunione ha perso un tratto audio.")
            if not {chunk["pcm_sha256"] for chunk in chunks} <= {
                call["pcm_sha256"] for call in requests
            }:
                raise RuntimeError(
                    "Un blocco della riunione non è stato inviato al riconoscitore."
                )
            save(work / "asr.json", rows)
            save(work / "quality.json", quality)
            save(work / "chunks.json", chunks)
            save(work / "requests.json", requests)
            save(
                work / "asr-audit.json",
                {
                    "complete_audio_coverage": True,
                    "chunks": len(chunks),
                    "requests": len(requests),
                    "chunk_spans": chunks,
                    "request_pcm_hashes": requests,
                },
            )
        finally:
            backend.stop()
    elif stage in {"ctc", "qwen"}:
        from core.english_alignment import align_ctc_rows, align_qwen_rows

        function = align_ctc_rows if stage == "ctc" else align_qwen_rows
        if stage == "ctc" and language != "en":
            raise ValueError("L'allineamento CTC inglese richiede la lingua en")
        name = "ctc-en" if stage == "ctc" else "qwen-aligner"
        rows, calls = function(
            audio,
            load(work / "asr.json"),
            models.path(name),
            **({"language": language} if stage == "qwen" else {}),
            progress=lambda index, total, rows, call: progress(
                int(100 * index / total)
            ),
        )
        save(work / f"{stage}.json", rows)
        save(work / f"{stage}-calls.json", calls)
    elif stage == "combine":
        from core.english_timing import combine_word_timings

        provenance = load(work / "provenance.json")
        qwen_rows = load(work / "qwen.json")
        rows, changes, clamps = combine_word_timings(
            load(work / "ctc.json") if language == "en" else qwen_rows,
            qwen_rows,
            provenance["frames"] / 16000,
        )
        if [row["text"] for row in rows] != [
            row["text"] for row in load(work / "asr.json")
        ]:
            raise RuntimeError("L'allineamento ha modificato il testo riconosciuto.")
        if (
            digest(source) != provenance["source_sha256"]
            or digest(audio) != provenance["pcm_sha256"]
        ):
            raise RuntimeError("L'audio è cambiato durante l'elaborazione della riunione.")
        save(
            work / "final.json",
            {
                "segments": rows,
                "quality": load(work / "quality.json"),
                "provenance": provenance,
                "changed_words": changes,
                "monotone_start_clamps": clamps,
                "source_audit": load(work / "asr-audit.json"),
            },
        )
    elif stage == "diar":
        from core.speaker_diarization import (
            DiarizationModelManager,
            SpeakerDiarizer,
            shutdown_diarization_runtime,
        )

        expected_root = models.path("community3").parent
        if (
            diarization_models is not None
            and diarization_models.resolve() != expected_root.resolve()
        ):
            raise ValueError(
                "La copia dei modelli delle riunioni non coincide con quella verificata."
            )
        model_hashes = models.verify(names=["community3"])
        diarizer = SpeakerDiarizer(DiarizationModelManager(expected_root))
        try:
            pipeline = diarizer._get_pipeline()
            configuration = models.manifest["diarization"]
            pipeline._segmentation.duration = configuration["acoustic_window"][
                "duration_s"
            ]
            pipeline._segmentation.step = configuration["acoustic_window"]["step_s"]
            pipeline.instantiate(configuration["parameters"])
            output = diarizer.run(
                audio, num_speakers=speakers if speakers > 0 else -1, progress=progress
            )
            save(
                work / "diarization.json",
                {
                    "exclusive": output.exclusive_segments,
                    "regular": output.speaker_segments,
                    "configuration": configuration,
                    "model_hashes": model_hashes,
                },
            )
            provenance = load(work / "provenance.json")
            if (
                digest(source) != provenance["source_sha256"]
                or digest(audio) != provenance["pcm_sha256"]
            ):
                raise RuntimeError("L'audio è cambiato durante il calcolo delle voci.")
        finally:
            shutdown_diarization_runtime()
    progress(100)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=[
            "download",
            "prepare",
            "prepare_diar",
            "asr",
            "ctc",
            "qwen",
            "combine",
            "diar",
        ],
        required=True,
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--diarization-models", type=Path)
    parser.add_argument("--speakers", type=int, default=0)
    parser.add_argument("--language", default="en")
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HUB_OFFLINE"] = "0" if args.stage == "download" else "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["ULTRATRANSCRIBR_EXPERIMENTAL_BOUNDARY_RECOVERY"] = "0"
    started = time.monotonic()
    try:
        run_stage(
            args.stage,
            args.source,
            args.work,
            EnglishModelManager(args.models),
            args.diarization_models,
            args.speakers,
            args.language,
        )
        save(
            args.work / f"{args.stage}-result.json",
            {"success": True, "elapsed_s": time.monotonic() - started},
        )
    except Exception as exc:
        save(
            args.work / f"{args.stage}-result.json",
            {"success": False, "error": str(exc)},
        )
        raise


if __name__ == "__main__":
    main()
