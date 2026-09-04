from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import numpy as np

import core.speaker_diarization as sd
from core.speaker_diarization import align_speakers, speaker_label


def test_align_speakers_assigns_dominant_temporal_overlap() -> None:
    transcript = [
        {"start": 0.0, "end": 4.0, "text": "Primo intervento"},
        {"start": 4.0, "end": 7.0, "text": "Secondo intervento"},
    ]
    diarization = [
        {"start": 0.0, "end": 3.6, "speaker_id": "SPEAKER_00"},
        {"start": 3.6, "end": 4.0, "speaker_id": "SPEAKER_01"},
        {"start": 4.0, "end": 7.0, "speaker_id": "SPEAKER_01"},
    ]

    review = align_speakers(transcript, diarization)

    assert review[0]["speaker_id"] == "SPEAKER_00"
    assert review[0]["uncertain"] is False
    assert review[0]["raw_text"] == review[0]["text"] == "Primo intervento"
    assert review[1]["speaker_id"] == "SPEAKER_01"


def test_align_speakers_marks_near_equal_overlap_uncertain() -> None:
    review = align_speakers(
        [{"start": 0.0, "end": 2.0, "text": "Voce sovrapposta"}],
        [
            {"start": 0.0, "end": 1.1, "speaker_id": "SPEAKER_00"},
            {"start": 0.9, "end": 2.0, "speaker_id": "SPEAKER_01"},
        ],
    )

    assert review[0]["speaker_id"] is None
    assert review[0]["uncertain"] is True
    assert review[0]["speaker_candidates"] == ["SPEAKER_00", "SPEAKER_01"]


def test_rerun_stabilizes_swapped_cluster_ids_by_temporal_overlap() -> None:
    previous = [
        {"start": 0.0, "end": 4.0, "speaker_id": "SPEAKER_00"},
        {"start": 4.0, "end": 8.0, "speaker_id": "SPEAKER_01"},
    ]
    rerun = [
        {"start": 0.0, "end": 4.0, "speaker_id": "SPEAKER_01"},
        {"start": 4.0, "end": 8.0, "speaker_id": "SPEAKER_00"},
    ]

    stable = sd.stabilize_speaker_ids(previous, rerun)

    assert stable == previous


def test_rerun_assigns_fresh_id_to_unmatched_new_speaker() -> None:
    previous = [
        {"start": 0.0, "end": 2.0, "speaker_id": "SPEAKER_00"},
        {"start": 2.0, "end": 4.0, "speaker_id": "SPEAKER_01"},
    ]
    rerun = [
        {"start": 0.0, "end": 2.0, "speaker_id": "SPEAKER_01"},
        {"start": 2.0, "end": 4.0, "speaker_id": "SPEAKER_00"},
        {"start": 4.0, "end": 6.0, "speaker_id": "SPEAKER_02"},
    ]

    stable = sd.stabilize_speaker_ids(previous, rerun)

    assert stable[0]["speaker_id"] == "SPEAKER_00"
    assert stable[1]["speaker_id"] == "SPEAKER_01"
    assert stable[2]["speaker_id"] == "SPEAKER_02"


def test_rerun_preserves_manual_text_only_for_same_raw_segment() -> None:
    previous = [
        {
            "start": 0.0,
            "end": 1.0,
            "raw_text": "Ciao mondo",
            "text": "Ciao a tutti",
            "speaker_id": "SPEAKER_00",
        }
    ]
    rerun = [
        {
            "start": 0.0,
            "end": 1.0,
            "raw_text": "Ciao mondo",
            "text": "Ciao mondo",
            "speaker_id": "SPEAKER_01",
        },
        {
            "start": 1.0,
            "end": 2.0,
            "raw_text": "Nuovo segmento",
            "text": "Nuovo segmento",
            "speaker_id": "SPEAKER_01",
        },
    ]

    preserved = sd.preserve_review_text(previous, rerun)

    assert preserved[0]["text"] == "Ciao a tutti"
    assert preserved[0]["speaker_id"] == "SPEAKER_01"
    assert preserved[1]["text"] == "Nuovo segmento"


def test_manual_speaker_names_only_change_display_label() -> None:
    names = {"SPEAKER_00": "Marco"}
    assert speaker_label("SPEAKER_00", names) == "Marco"
    assert speaker_label("SPEAKER_01", names) == "Speaker 2"
    assert speaker_label(None, names) == "Speaker ?"


class _Turn:
    def __init__(self, start: float, end: float) -> None:
        self.start = start
        self.end = end


class _Annotation:
    def itertracks(self, yield_label=False):
        assert yield_label is True
        yield _Turn(0.0, 1.0), None, "voice-B"
        yield _Turn(1.0, 2.0), None, "voice-A"
        yield _Turn(2.0, 3.0), None, "voice-B"


class _RegularAnnotation:
    def itertracks(self, yield_label=False):
        assert yield_label is True
        yield _Turn(0.0, 1.1), None, "voice-B"
        yield _Turn(0.8, 2.0), None, "voice-A"
        yield _Turn(2.0, 3.0), None, "voice-B"


def test_annotation_is_canonicalized_to_stable_session_speaker_ids() -> None:
    assert sd._annotation_to_segments(_Annotation()) == [
        {"start": 0.0, "end": 1.0, "speaker_id": "SPEAKER_00"},
        {"start": 1.0, "end": 2.0, "speaker_id": "SPEAKER_01"},
        {"start": 2.0, "end": 3.0, "speaker_id": "SPEAKER_00"},
    ]


def test_model_status_requires_complete_payload_and_revision_marker(tmp_path: Path) -> None:
    manager = sd.DiarizationModelManager(tmp_path)
    model = manager.model_dir
    model.mkdir(parents=True)
    (model / "config.yaml").write_text("pipeline: {}\n", encoding="utf-8")
    for name in ("segmentation", "embedding", "plda"):
        directory = model / name
        directory.mkdir()
        (directory / "payload.bin").write_bytes(b"x")
    assert manager.status()["ready"] is False
    manager.marker.write_text(
        json.dumps({"repo_id": sd.COMMUNITY_REPO_ID, "revision": "abc123"}),
        encoding="utf-8",
    )
    status = manager.status()
    assert status["ready"] is True
    assert status["revision"] == "abc123"


def test_diarizer_returns_regular_and_exclusive_with_shared_speaker_ids(monkeypatch, tmp_path) -> None:
    captured = {}

    class _Waveform:
        def unsqueeze(self, dim):
            assert dim == 0
            return self

    torch = ModuleType("torch")
    torch.from_numpy = lambda array: _Waveform()
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr(sd, "get_torch_xpu_device", lambda: "xpu:0")
    monkeypatch.setattr(
        sd.sf,
        "read",
        lambda *args, **kwargs: (np.zeros((16000, 1), dtype=np.float32), 16000),
    )

    class _Output:
        exclusive_speaker_diarization = _Annotation()
        speaker_diarization = _RegularAnnotation()

    class _Pipeline:
        def __call__(self, payload, **kwargs):
            captured["payload"] = payload
            captured["kwargs"] = kwargs
            return _Output()

    diarizer = sd.SpeakerDiarizer(sd.DiarizationModelManager(tmp_path))
    monkeypatch.setattr(diarizer, "_get_pipeline", lambda: _Pipeline())

    result = diarizer.run("meeting.flac", num_speakers=4)

    assert captured["kwargs"] == {"num_speakers": 4}
    assert captured["payload"]["sample_rate"] == 16000
    assert result.exclusive_segments[0]["speaker_id"] == "SPEAKER_00"
    assert result.exclusive_segments[1]["speaker_id"] == "SPEAKER_01"
    assert result.speaker_segments[0]["speaker_id"] == "SPEAKER_00"
    assert result.speaker_segments[1]["speaker_id"] == "SPEAKER_01"
    assert result.speaker_segments[0]["end"] == 1.1
