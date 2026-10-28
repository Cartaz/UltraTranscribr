import hashlib
import json
from threading import Event

import pytest

from core.english_models import EnglishModelManager, EnglishPipelineCancelled


def manager(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "name": "asr",
                    "repository": "fixture/model",
                    "revision": "frozen-revision",
                        "files": [
                            {
                                "name": "model.bin",
                                "bytes": 3,
                                "sha256": hashlib.sha256(b"abc").hexdigest(),
                            }
                        ],
                    }
                ]
            }
        )
    )
    return EnglishModelManager(tmp_path / "models", manifest_path=manifest)


def test_assets_are_not_accepted_only_because_their_size_matches(tmp_path):
    models = manager(tmp_path)
    assert models.missing() == ["asr"]
    models.path("asr").mkdir(parents=True)
    path = models.path("asr") / "model.bin"
    path.write_bytes(b"bad")
    assert models.missing() == []
    with pytest.raises(RuntimeError, match="incompleto"):
        models.verify()
    path.write_bytes(b"abc")
    progress = []
    assert (
        models.verify(progress=progress.append)["asr/model.bin"]
        == hashlib.sha256(b"abc").hexdigest()
    )
    assert progress[-1] == 100


def test_model_verification_honors_cancellation_before_reading_assets(tmp_path):
    models = manager(tmp_path)
    cancel = Event()
    cancel.set()
    with pytest.raises(EnglishPipelineCancelled):
        models.verify(cancel=cancel)


def test_preparation_reuses_verified_assets_and_repairs_corrupt_files(tmp_path, monkeypatch):
    models = manager(tmp_path)
    models.path("asr").mkdir(parents=True)
    path = models.path("asr") / "model.bin"
    path.write_bytes(b"abc")
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        path.write_bytes(b"abc")

    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    models.download(cancel=Event())
    assert calls == []
    path.write_bytes(b"bad")
    models.download(cancel=Event())
    assert len(calls) == 1
    assert calls[0]["force_download"] is True
    assert calls[0]["revision"] == "frozen-revision"
    assert models.verify()
