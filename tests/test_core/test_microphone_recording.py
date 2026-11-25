from pathlib import Path

import numpy as np
import soundfile as sf

from core.microphone_recording import MicrophoneRecorder
from core.session_recordings import delete_recording, recording_info


def test_startup_recovery_cannot_consume_an_active_recording(tmp_path):
    recorder = MicrophoneRecorder("active-meeting", root=tmp_path)
    samples = np.full(8000, 0.1, dtype=np.float32)
    recorder.write(samples)
    assert MicrophoneRecorder.recover_orphaned(tmp_path) == []
    assert recorder.part_path.is_file()
    recorder.write(samples)
    info = recorder.finalize()
    assert info.duration_s == 1.0
    audio, rate = sf.read(info.path)
    assert len(audio) == rate == 16000


def test_abandoned_journal_releases_ownership_for_recovery(tmp_path):
    recorder = MicrophoneRecorder("abandoned", root=tmp_path)
    recorder.write(np.full(8000, 0.1, dtype=np.float32))
    recorder.abandon()
    recovered = MicrophoneRecorder.recover_orphaned(tmp_path)
    assert len(recovered) == 1
    assert recovered[0].duration_s == 0.5


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


def test_silent_48k_track_leaves_no_format_sidecar(tmp_path) -> None:
    recorder = MicrophoneRecorder("silent-source", root=tmp_path, sample_rate=48000)
    recorder.start()
    assert recorder.finalize() is None
    # The hidden journal lock is a deliberate stable inode; nothing else stays.
    assert [p.name for p in tmp_path.iterdir() if not p.name.endswith(".lock")] == []


def test_rate_marker_is_written_before_the_journal_exists(tmp_path, monkeypatch) -> None:
    import builtins

    recorder = MicrophoneRecorder("crash-window", root=tmp_path, sample_rate=48000)
    real_open = builtins.open
    seen = []

    def tracking_open(path, mode="r", *args, **kwargs):
        if str(path).endswith(".pcm.part"):
            seen.append(recorder.part_path.with_name(
                recorder.part_path.name + ".format.json"
            ).is_file())
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", tracking_open)
    recorder.start()
    monkeypatch.setattr(builtins, "open", real_open)
    recorder.abandon()
    assert seen == [True]
