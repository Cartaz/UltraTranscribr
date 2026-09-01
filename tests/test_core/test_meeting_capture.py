from pathlib import Path

import numpy as np
import soundfile as sf

from config.constants import ProcessDefaults
from core.meeting_capture import mix_recordings, normalize_media_to_flac, recording_info


def _write_flac(path: Path, value: float, seconds: float) -> None:
    frames = int(ProcessDefaults.SAMPLE_RATE * seconds)
    sf.write(
        path,
        np.full(frames, value, dtype=np.float32),
        ProcessDefaults.SAMPLE_RATE,
        subtype="PCM_16",
        format="FLAC",
    )


def test_mix_recordings_preserves_source_offsets_without_loading_full_session(tmp_path: Path) -> None:
    first = tmp_path / "first.flac"
    second = tmp_path / "second.flac"
    target = tmp_path / "meeting.flac"
    _write_flac(first, 0.4, 0.5)
    _write_flac(second, -0.2, 0.5)

    info = mix_recordings(
        [(recording_info(first), 0.0), (recording_info(second), 0.25)],
        target,
    )

    assert abs(info.duration_s - 0.75) < 0.01
    audio, sample_rate = sf.read(target, dtype="float32", always_2d=False)
    assert sample_rate == ProcessDefaults.SAMPLE_RATE
    quarter = ProcessDefaults.SAMPLE_RATE // 4
    assert np.mean(audio[:quarter]) > 0.35
    assert 0.05 < np.mean(audio[quarter : quarter * 2]) < 0.15
    assert np.mean(audio[quarter * 2 :]) < -0.15


def test_normalize_media_fallback_outputs_canonical_mono_16khz(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "phone.wav"
    target = tmp_path / "normalized.flac"
    frames = 2000
    stereo = np.column_stack(
        (
            np.linspace(-0.2, 0.2, frames, dtype=np.float32),
            np.linspace(0.2, -0.2, frames, dtype=np.float32),
        )
    )
    sf.write(source, stereo, 8000)
    monkeypatch.setattr("core.meeting_capture.shutil.which", lambda _name: None)

    info = normalize_media_to_flac(source, target)

    assert info.sample_rate == ProcessDefaults.SAMPLE_RATE
    assert info.channels == 1
    assert abs(info.duration_s - 0.25) < 0.02
    normalized = sf.info(target)
    assert normalized.samplerate == ProcessDefaults.SAMPLE_RATE
    assert normalized.channels == 1
    assert normalized.format == "FLAC"
