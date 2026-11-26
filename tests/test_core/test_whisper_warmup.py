"""A throwaway request absorbs the first-inference GPU setup after a start."""

import urllib.error

import core.whisper_backend as backend_module
from config.settings import Settings
from core.whisper_backend import WhisperBackend


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b'{"text": ""}'


def test_warmup_runs_the_encoder_with_the_real_decoding_settings(monkeypatch):
    sent = []

    def urlopen(request, timeout):
        sent.append((request.full_url, request.data, timeout))
        return _Response()

    monkeypatch.setattr(backend_module.urllib.request, "urlopen", urlopen)
    backend = WhisperBackend(Settings(beam_size=3))
    backend._warm_up(None, "http://127.0.0.1:9/inference")

    url, body, timeout = sent[0]
    assert url.endswith("/inference")
    assert b'name="vad"\r\n\r\nfalse' in body  # server VAD would skip noise
    assert b'name="beam_size"\r\n\r\n3' in body
    assert body.count(b"RIFF") == 1 and timeout == backend_module._WARMUP_TIMEOUT_S


def test_warmup_failure_is_harmless(monkeypatch):
    def urlopen(request, timeout):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(backend_module.urllib.request, "urlopen", urlopen)
    WhisperBackend(Settings())._warm_up(None, "http://127.0.0.1:9/inference")


def test_dictation_starts_the_backend_without_a_warmup():
    from unittest.mock import MagicMock

    from core.app_controller import AppController

    controller = AppController.__new__(AppController)
    controller.ensure_backend_started = MagicMock()
    controller._ensure_backend_for_dictation(Settings())
    assert controller.ensure_backend_started.call_args.kwargs["warm_up"] is False


def test_spawn_warms_up_only_when_the_lifecycle_call_asked(monkeypatch, tmp_path):
    backend = WhisperBackend(Settings())
    warmups = []
    monkeypatch.setattr(backend, "_start_warmup", lambda: warmups.append(True))
    monkeypatch.setattr(backend, "_wait_for_health", lambda: None)
    monkeypatch.setattr(backend, "_build_cmd", lambda *_: ["true"])
    monkeypatch.setattr(backend, "_build_env", lambda: {})
    monkeypatch.setattr(backend, "_server_log_path", lambda: tmp_path / "server.log")
    monkeypatch.setattr(backend_module.subprocess, "Popen", lambda *a, **k: type("P", (), {"poll": lambda self: 0})())
    backend._model_path = tmp_path / "model.bin"
    backend._server_binary = tmp_path / "whisper-server"
    backend._vad_model_path = tmp_path / "vad.bin"

    backend._warm_up_on_spawn = False  # as left by a Dictation cold start
    backend._spawn(False)
    assert warmups == []
    # A later Live respawn for another VAD mode decides for itself.
    backend.ensure_vad_mode(True, warm_up=True)
    assert warmups == [True]
