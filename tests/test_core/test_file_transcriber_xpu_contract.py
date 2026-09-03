from unittest.mock import MagicMock

from config.settings import Settings
from core.file_transcriber import FileTranscriberThread


def test_requested_vocal_isolation_failure_does_not_transcribe_original(monkeypatch) -> None:
    worker = FileTranscriberThread(
        "song.wav",
        MagicMock(),
        Settings(),
        song_mode=True,
        isolate_vocals_flag=True,
    )
    transcribe = MagicMock()
    monkeypatch.setattr(
        worker,
        "_run_vocal_isolation",
        MagicMock(side_effect=RuntimeError("XPU failure")),
    )
    monkeypatch.setattr(worker, "_transcribe_progressively", transcribe)
    monkeypatch.setattr(worker, "_cleanup", lambda: None)

    worker.run()

    transcribe.assert_not_called()
    assert worker._terminal_state == "error"
