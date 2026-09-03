from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_diarization_has_no_sherpa_or_cpu_backend() -> None:
    source = (ROOT / "core" / "speaker_diarization.py").read_text(encoding="utf-8")
    assert "speaker-diarization-community-1" in source
    assert "exclusive_speaker_diarization" in source
    assert "get_torch_xpu_device" in source
    assert "sherpa_onnx" not in source
    assert "FastClusteringConfig" not in source
    assert 'device="cpu"' not in source
