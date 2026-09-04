from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_validates_paths_and_speaker_count_in_domain_layer() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")

    assert "if not path.is_file():" in source
    assert "if count < 0 or count > 20:" in source
    assert "raise FileNotFoundError" in source
    assert "raise ValueError" in source
