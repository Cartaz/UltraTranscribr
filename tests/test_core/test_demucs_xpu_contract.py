from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_file_worker_has_no_demucs_cpu_or_original_audio_fallback() -> None:
    source = (ROOT / "core" / "file_transcriber.py").read_text(encoding="utf-8")
    assert 'device="cpu"' not in source
    assert "Demucs non disponibile; continuo col file originale" not in source
    assert "is_demucs_available" not in source


def test_vocal_isolator_has_one_xpu_inference_path() -> None:
    isolator = (ROOT / "core" / "vocal_isolator.py").read_text(encoding="utf-8")
    io = (ROOT / "core" / "vocal_isolator_io.py").read_text(encoding="utf-8")
    assert "get_torch_xpu_device" in isolator
    assert "isolate_vocals_xpu" in isolator
    assert "demucs.api" not in isolator
    assert "demucs.separate" not in isolator
    assert "demucs_infer" in io
    assert "apply_model" in io
