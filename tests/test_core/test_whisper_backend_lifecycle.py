from __future__ import annotations

import logging
import subprocess
from unittest.mock import MagicMock

from config.constants import AppMeta
from config.settings import Settings
from core.whisper_backend import WhisperBackend


def test_backend_log_lives_under_xdg_cache(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setattr(AppMeta, "CACHE_DIR", cache)
    backend = WhisperBackend(Settings(), tmp_path / "project")

    path = backend._server_log_path()

    assert path == cache / "logs" / "whisper-server.log"
    assert path.parent.is_dir()


def test_cleanup_reports_process_that_survives_kill(caplog, tmp_path) -> None:
    backend = WhisperBackend(Settings(), tmp_path)
    process = MagicMock()
    process.poll.return_value = None
    process.wait.side_effect = [
        subprocess.TimeoutExpired("whisper-server", 3.0),
        subprocess.TimeoutExpired("whisper-server", 2.0),
    ]
    backend._process = process

    with caplog.at_level(logging.WARNING, logger="core.whisper_backend"):
        backend._cleanup_process()

    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert "non reaped" in caplog.text


def test_cleanup_reports_terminate_oserror(caplog, tmp_path) -> None:
    backend = WhisperBackend(Settings(), tmp_path)
    process = MagicMock()
    process.poll.return_value = None
    process.terminate.side_effect = OSError("permission denied")
    backend._process = process

    with caplog.at_level(logging.WARNING, logger="core.whisper_backend"):
        backend._cleanup_process()

    assert "Terminate/reap" in caplog.text
    assert "permission denied" in caplog.text
