"""Offline speaker diarization and timestamp alignment for Meeting sessions."""
from __future__ import annotations

import logging
import os
import shutil
import tarfile
import threading
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import soundfile as sf

from config.constants import AppMeta, ProcessDefaults
from core.transcript_export import normalize_segments

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[str, int], None]

SEGMENTATION_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)
EMBEDDING_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/"
    "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
)


class DiarizationModelManager:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root or AppMeta.DIARIZATION_MODELS_DIR)
        self.segmentation = self.root / "pyannote-segmentation-3.0.onnx"
        self.embedding = self.root / "3dspeaker-eres2net-base-16k.onnx"
        self._lock = threading.Lock()

    def status(self) -> dict[str, Any]:
        return {
            "ready": self.segmentation.is_file() and self.embedding.is_file(),
            "segmentation": str(self.segmentation),
            "embedding": str(self.embedding),
        }

    def ensure_models(self, progress: Optional[ProgressCallback] = None) -> dict[str, Any]:
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            if not self.segmentation.is_file():
                archive = self.root / "segmentation.tar.bz2.part"
                self._download(SEGMENTATION_URL, archive, "segmentation", progress)
                try:
                    with tarfile.open(archive, "r:bz2") as tar:
                        member = next(
                            (item for item in tar.getmembers() if item.isfile() and item.name.endswith("/model.onnx")),
                            None,
                        )
                        if member is None:
                            raise RuntimeError("model.onnx non trovato nell'archivio diarizzazione")
                        source = tar.extractfile(member)
                        if source is None:
                            raise RuntimeError("impossibile leggere il modello diarizzazione")
                        temp = self.segmentation.with_suffix(".onnx.tmp")
                        with open(temp, "wb") as target:
                            shutil.copyfileobj(source, target)
                            target.flush()
                            os.fsync(target.fileno())
                        os.replace(temp, self.segmentation)
                finally:
                    archive.unlink(missing_ok=True)
            if not self.embedding.is_file():
                part = self.embedding.with_suffix(".onnx.part")
                self._download(EMBEDDING_URL, part, "embedding", progress)
                os.replace(part, self.embedding)
        return self.status()

    @staticmethod
    def _download(
        url: str,
        target: Path,
        label: str,
        progress: Optional[ProgressCallback],
    ) -> None:
        temp = Path(target)
        temp.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "UltraTranscribr/1"})
        with urllib.request.urlopen(request, timeout=60) as response, open(temp, "wb") as handle:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                if progress:
                    percent = int(downloaded * 100 / total) if total > 0 else 0
                    progress(label, max(0, min(100, percent)))
            handle.flush()
            os.fsync(handle.fileno())
        if progress:
            progress(label, 100)


class SpeakerDiarizer:
    def __init__(self, models: Optional[DiarizationModelManager] = None) -> None:
        self.models = models or DiarizationModelManager()

    def run(
        self,
        audio_path: Path | str,
        *,
        num_speakers: int = -1,
        cluster_threshold: float = 0.5,
        progress: Optional[Callable[[int], None]] = None,
    ) -> list[dict[str, Any]]:
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError(
                "Diarizzazione non disponibile: installa la dipendenza sherpa-onnx"
            ) from exc

        status = self.models.ensure_models()
        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=status["segmentation"]
                ),
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=status["embedding"],
            ),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=int(num_speakers),
                threshold=float(cluster_threshold),
            ),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        if not config.validate():
            raise RuntimeError("configurazione diarizzazione non valida")
        diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)

        audio, sample_rate = sf.read(str(audio_path), dtype="float32", always_2d=True)
        if audio.size == 0:
            raise RuntimeError("registrazione riunione vuota")
        mono = np.mean(audio, axis=1, dtype=np.float32)
        if int(sample_rate) != int(diarizer.sample_rate):
            raise RuntimeError(
                f"la diarizzazione richiede {diarizer.sample_rate} Hz; ricevuti {sample_rate} Hz"
            )

        def callback(done: int, total: int) -> int:
            if progress and total:
                progress(max(0, min(100, int(done * 100 / total))))
            return 0

        result = diarizer.process(mono, callback=callback).sort_by_start_time()
        segments: list[dict[str, Any]] = []
        for item in result:
            segments.append(
                {
                    "start": round(float(item.start), 3),
                    "end": round(float(item.end), 3),
                    "speaker_id": f"SPEAKER_{int(item.speaker):02d}",
                }
            )
        if progress:
            progress(100)
        return segments


def align_speakers(
    transcript_segments: list[dict[str, Any]],
    diarization_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create editable review segments while preserving raw Whisper segments.

    Speaker attribution is based on temporal overlap. When the two strongest
    speakers have nearly equal overlap, the segment is explicitly marked
    uncertain instead of pretending the identity is certain.
    """
    transcript = normalize_segments(transcript_segments)
    diarization = [
        {
            "start": max(0.0, float(item.get("start", 0.0))),
            "end": max(0.0, float(item.get("end", 0.0))),
            "speaker_id": str(item.get("speaker_id") or ""),
        }
        for item in diarization_segments
        if float(item.get("end", 0.0)) > float(item.get("start", 0.0))
        and str(item.get("speaker_id") or "")
    ]
    output: list[dict[str, Any]] = []
    for segment in transcript:
        start = float(segment["start"])
        end = float(segment["end"])
        overlaps: dict[str, float] = {}
        for turn in diarization:
            overlap = max(0.0, min(end, turn["end"]) - max(start, turn["start"]))
            if overlap > 0:
                speaker = turn["speaker_id"]
                overlaps[speaker] = overlaps.get(speaker, 0.0) + overlap
        ranked = sorted(overlaps.items(), key=lambda item: (-item[1], item[0]))
        speaker_id: Optional[str] = ranked[0][0] if ranked else None
        uncertain = False
        candidates = [speaker for speaker, _ in ranked[:2]]
        if len(ranked) > 1 and ranked[0][1] > 0:
            uncertain = ranked[1][1] / ranked[0][1] >= 0.8
            if uncertain:
                speaker_id = None
        text = str(segment.get("text") or "").strip()
        output.append(
            {
                "start": start,
                "end": end,
                "raw_text": text,
                "text": text,
                "speaker_id": speaker_id,
                "uncertain": uncertain,
                "speaker_candidates": candidates,
            }
        )
    return output


def speaker_label(speaker_id: Optional[str], names: dict[str, str]) -> str:
    if not speaker_id:
        return "Speaker ?"
    custom = str(names.get(speaker_id) or "").strip()
    if custom:
        return custom
    try:
        number = int(str(speaker_id).rsplit("_", 1)[-1]) + 1
    except ValueError:
        return str(speaker_id)
    return f"Speaker {number}"
