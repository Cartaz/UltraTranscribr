"""High-accuracy local speaker diarization for Meeting sessions.

The Meeting pipeline uses pyannote Community-1 on the shared PyTorch Intel XPU
runtime. Both regular and exclusive diarization are retained: exclusive timing
owns transcript assignment, while regular timing exposes true overlapping
speech for review. There is no lightweight/CPU diarization fallback.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import soundfile as sf

from config.constants import AppMeta, ProcessDefaults
from core.meeting_alignment import (
    align_speakers,
    preserve_review_edits,
    preserve_review_text,
    speaker_label,
    stabilize_speaker_ids,
)
from core.torch_xpu import get_torch_xpu_device

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[str, int], None]

COMMUNITY_REPO_ID = "pyannote/speaker-diarization-community-1"
COMMUNITY_MODEL_NAME = "community-1"
_MARKER_NAME = ".ultratranscribr-model.json"
_REQUIRED_DIRECTORIES = ("segmentation", "embedding", "plda")


@dataclass(frozen=True)
class DiarizationResult:
    """Serializable timing returned by one Community-1 inference."""

    exclusive_segments: list[dict[str, Any]]
    speaker_segments: list[dict[str, Any]]


class DiarizationModelManager:
    """Own the app-local, fully offline Community-1 snapshot."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root or AppMeta.DIARIZATION_MODELS_DIR)
        self.model_dir = self.root / COMMUNITY_MODEL_NAME
        self.marker = self.model_dir / _MARKER_NAME
        self._lock = threading.Lock()

    def status(self) -> dict[str, Any]:
        revision = ""
        if self.marker.is_file():
            try:
                payload = json.loads(self.marker.read_text(encoding="utf-8"))
                revision = str(payload.get("revision") or "")
            except (OSError, json.JSONDecodeError, TypeError):
                revision = ""
        return {
            "ready": self._is_complete(self.model_dir) and bool(revision),
            "model": str(self.model_dir),
            "repo_id": COMMUNITY_REPO_ID,
            "revision": revision,
        }

    def ensure_models(self, progress: Optional[ProgressCallback] = None) -> dict[str, Any]:
        with self._lock:
            current = self.status()
            if current["ready"]:
                return current

            try:
                from huggingface_hub import HfApi, get_token, snapshot_download
            except ImportError as exc:
                raise RuntimeError(
                    "huggingface-hub non disponibile; esegui ./install.sh"
                ) from exc

            token = get_token()
            if not token:
                raise RuntimeError(
                    "Community-1 richiede una tantum l'accettazione delle condizioni su "
                    "Hugging Face e un token locale. Accetta il modello "
                    f"'{COMMUNITY_REPO_ID}', poi esegui `.venv/bin/hf auth login` e riprova."
                )

            self.root.mkdir(parents=True, exist_ok=True)
            staging = self.root / f".{COMMUNITY_MODEL_NAME}.download"
            shutil.rmtree(staging, ignore_errors=True)
            if progress:
                progress(COMMUNITY_MODEL_NAME, 0)

            try:
                info = HfApi().model_info(COMMUNITY_REPO_ID, revision="main", token=token)
                revision = str(info.sha or "").strip()
                if not revision:
                    raise RuntimeError("Hugging Face non ha restituito la revisione del modello")
                snapshot_download(
                    repo_id=COMMUNITY_REPO_ID,
                    revision=revision,
                    local_dir=staging,
                    token=token,
                )
                if not self._has_model_payload(staging):
                    raise RuntimeError("snapshot Community-1 incompleto")
                marker = staging / _MARKER_NAME
                marker_payload = json.dumps(
                    {"repo_id": COMMUNITY_REPO_ID, "revision": revision},
                    ensure_ascii=False,
                    indent=2,
                ) + "\n"
                with marker.open("w", encoding="utf-8") as handle:
                    handle.write(marker_payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                shutil.rmtree(self.model_dir, ignore_errors=True)
                os.replace(staging, self.model_dir)
            except Exception as exc:
                shutil.rmtree(staging, ignore_errors=True)
                raise RuntimeError(
                    "Download Community-1 fallito. Verifica di aver accettato le condizioni "
                    "del modello e che il token Hugging Face sia valido."
                ) from exc

            if progress:
                progress(COMMUNITY_MODEL_NAME, 100)
            return self.status()

    @classmethod
    def _has_model_payload(cls, model_dir: Path) -> bool:
        if not (model_dir / "config.yaml").is_file():
            return False
        for name in _REQUIRED_DIRECTORIES:
            directory = model_dir / name
            try:
                if not directory.is_dir() or not any(
                    path.is_file() and path.stat().st_size > 0
                    for path in directory.rglob("*")
                ):
                    return False
            except OSError:
                return False
        return True

    @classmethod
    def _is_complete(cls, model_dir: Path) -> bool:
        return cls._has_model_payload(model_dir) and (model_dir / _MARKER_NAME).is_file()


class SpeakerDiarizer:
    """Run pyannote Community-1 on XPU and return both diarization timelines."""

    def __init__(self, models: Optional[DiarizationModelManager] = None) -> None:
        self.models = models or DiarizationModelManager()
        self._pipeline: Any | None = None
        self._pipeline_path: Path | None = None
        self._pipeline_lock = threading.Lock()

    def _get_pipeline(self) -> Any:
        status = self.models.ensure_models()
        model_path = Path(str(status["model"]))
        with self._pipeline_lock:
            if self._pipeline is not None and self._pipeline_path == model_path:
                return self._pipeline
            try:
                from pyannote.audio import Pipeline
            except ImportError as exc:
                raise RuntimeError(
                    "pyannote.audio non disponibile; esegui ./install.sh"
                ) from exc
            pipeline = Pipeline.from_pretrained(str(model_path))
            if pipeline is None:
                raise RuntimeError("impossibile caricare Community-1 dalla cache locale")
            pipeline.to(get_torch_xpu_device())
            self._pipeline = pipeline
            self._pipeline_path = model_path
            return pipeline

    def run(
        self,
        audio_path: Path | str,
        *,
        num_speakers: int = -1,
        progress: Optional[Callable[[int], None]] = None,
    ) -> DiarizationResult:
        pipeline = self._get_pipeline()
        device = get_torch_xpu_device()
        del device

        audio, sample_rate = sf.read(str(audio_path), dtype="float32", always_2d=True)
        if audio.size == 0:
            raise RuntimeError("registrazione riunione vuota")
        mono = np.mean(audio, axis=1, dtype=np.float32)
        if int(sample_rate) != ProcessDefaults.SAMPLE_RATE:
            from core.audio_resampler import resample

            mono = resample(mono, int(sample_rate), ProcessDefaults.SAMPLE_RATE)
        mono = np.asarray(mono, dtype=np.float32)

        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("PyTorch XPU non disponibile; esegui ./install.sh") from exc
        waveform = torch.from_numpy(mono.copy()).unsqueeze(0)
        kwargs: dict[str, int] = {}
        if int(num_speakers) > 0:
            kwargs["num_speakers"] = int(num_speakers)

        if progress:
            progress(5)
        try:
            output = pipeline(
                {"waveform": waveform, "sample_rate": ProcessDefaults.SAMPLE_RATE},
                **kwargs,
            )
        except Exception as exc:
            raise RuntimeError(f"Diarizzazione Community-1/XPU fallita: {exc}") from exc

        exclusive = getattr(output, "exclusive_speaker_diarization", None)
        if exclusive is None:
            raise RuntimeError("Community-1 non ha restituito exclusive_speaker_diarization")
        speaker_ids: dict[str, str] = {}
        exclusive_segments = _annotation_to_segments(exclusive, speaker_ids=speaker_ids)
        if not exclusive_segments:
            raise RuntimeError("Community-1 non ha rilevato segmenti vocali")

        regular = getattr(output, "speaker_diarization", None)
        if regular is None:
            logger.warning(
                "Community-1 non ha restituito speaker_diarization; "
                "rilevamento overlap non disponibile"
            )
            speaker_segments = [dict(item) for item in exclusive_segments]
        else:
            speaker_segments = _annotation_to_segments(regular, speaker_ids=speaker_ids)
            if not speaker_segments:
                speaker_segments = [dict(item) for item in exclusive_segments]

        if progress:
            progress(100)
        return DiarizationResult(
            exclusive_segments=exclusive_segments,
            speaker_segments=speaker_segments,
        )


def _annotation_to_segments(
    annotation: Any,
    *,
    speaker_ids: Optional[dict[str, str]] = None,
) -> list[dict[str, Any]]:
    rows: list[tuple[float, float, str]] = []
    if hasattr(annotation, "itertracks"):
        iterator = annotation.itertracks(yield_label=True)
        for turn, _track, label in iterator:
            start = max(0.0, float(turn.start))
            end = max(start, float(turn.end))
            if end > start:
                rows.append((start, end, str(label)))
    else:
        for item in annotation:
            try:
                turn, label = item
                start = max(0.0, float(turn.start))
                end = max(start, float(turn.end))
            except (TypeError, ValueError, AttributeError):
                continue
            if end > start:
                rows.append((start, end, str(label)))

    rows.sort(key=lambda item: (item[0], item[1], item[2]))
    mapping = speaker_ids if speaker_ids is not None else {}
    output: list[dict[str, Any]] = []
    for start, end, raw_label in rows:
        speaker = mapping.setdefault(raw_label, f"SPEAKER_{len(mapping):02d}")
        output.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "speaker_id": speaker,
            }
        )
    return output
