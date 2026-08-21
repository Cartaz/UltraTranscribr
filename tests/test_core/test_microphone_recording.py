from pathlib import Path

import numpy as np
import soundfile as sf

from core.microphone_recording import MicrophoneRecorder
from core.session_recordings import delete_recording, recording_info


def test_recorder_finalizes_pcm_journal_to_lossless_flac(tmp_path: Path) -> None:
    recorder = MicrophoneRecorder("live-session", root=tmp_path)
    samples = np.linspace(-0.75, 0.75, 16000, dtype=np.float32)

    recorder.start()
    recorder.write(samples[:8000])
    recorder.write(samples[8000:])
    info = recorder.finalize()

    assert info is not None
    assert Path(info.path) == tmp_path / "live-session.flac"
    assert not (tmp_path / "live-session.pcm.part").exists()
    audio, rate = sf.read(info.path, dtype="float32")
    assert rate == 16000
    assert len(audio) == 16000
    assert info.duration_s == 1.0
    assert np.max(np.abs(audio - samples)) < 1e-4


def test_orphan_pcm_is_recovered_and_tolerates_partial_final_byte(tmp_path: Path) -> None:
    pcm = (np.ones(8000, dtype=np.int16) * 1024).astype("<i2").tobytes()
    part = tmp_path / "meeting-1.pcm.part"
    part.write_bytes(pcm + b"x")

    recovered = MicrophoneRecorder.recover_orphaned(tmp_path)

    assert len(recovered) == 1
    assert recovered[0].duration_s == 0.5
    assert (tmp_path / "meeting-1.flac").is_file()
    assert not part.exists()


def test_session_recording_lookup_and_delete_are_scoped_by_session_id(tmp_path: Path) -> None:
    recorder = MicrophoneRecorder("safe-id", root=tmp_path)
    recorder.write(np.zeros(1600, dtype=np.float32))
    recorder.finalize()

    info = recording_info("safe-id", tmp_path)
    assert info["exists"] is True
    assert info["channels"] == 1
    assert info["sample_rate"] == 16000

    assert delete_recording("safe-id", tmp_path) is True
    assert recording_info("safe-id", tmp_path)["exists"] is False


def test_invalid_recording_session_id_cannot_escape_root(tmp_path: Path) -> None:
    try:
        recording_info("../escape", tmp_path)
    except ValueError as exc:
        assert "session id" in str(exc)
    else:
        raise AssertionError("path traversal id must be rejected")
