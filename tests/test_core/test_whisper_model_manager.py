"""Tests for managed Whisper model inventory and downloads."""
from __future__ import annotations

from pathlib import Path

import pytest

import core.whisper_models as whisper_models
from core.whisper_models import WhisperModelManager


class FakeResponse:
    def __init__(self, chunks: list[bytes], *, status: int, headers: dict[str, str]) -> None:
        self._chunks = list(chunks)
        self.status = status
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _size: int = -1) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


def _small_medium(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(whisper_models._MIN_MODEL_BYTES, "medium", 4)
    monkeypatch.setattr(whisper_models, "_ASR_REPOS", ["example/repo"])


def test_ui_inventory_is_limited_and_does_not_rehash_large_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _small_medium(monkeypatch)
    manager = WhisperModelManager(tmp_path)
    target = tmp_path / "ggml-medium.bin"
    target.write_bytes(b"abcd")
    manager._sha_path(target).write_text("saved-hash\n", encoding="ascii")

    monkeypatch.setattr(manager, "_sha256", lambda _path: (_ for _ in ()).throw(AssertionError("rehash")))
    info = manager.get_model_info("medium")

    assert manager.ui_model_choices() == ("large-v3", "large-v3-turbo", "medium")
    assert info["installed"] is True
    assert info["verified"] is True
    assert info["size_bytes"] == 4


def test_manual_download_reports_real_byte_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _small_medium(monkeypatch)
    manager = WhisperModelManager(tmp_path)
    calls: list[tuple[int, int | None]] = []

    monkeypatch.setattr(
        whisper_models.urllib.request,
        "urlopen",
        lambda _req, timeout=30: FakeResponse(
            [b"abcd", b""], status=200, headers={"Content-Length": "4"}
        ),
    )

    path = manager.download_model("medium", lambda done, total: calls.append((done, total)))

    assert path.read_bytes() == b"abcd"
    assert calls[0] == (0, 4)
    assert (4, 4) in calls
    assert manager._sha_path(path).is_file()
    assert not path.with_name(path.name + ".part").exists()


def test_manual_download_resumes_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _small_medium(monkeypatch)
    manager = WhisperModelManager(tmp_path)
    target = tmp_path / "ggml-medium.bin"
    part = target.with_name(target.name + ".part")
    tmp_path.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"ab")
    seen_range: list[str | None] = []
    progress: list[tuple[int, int | None]] = []

    def fake_urlopen(req, timeout=30):
        seen_range.append(req.get_header("Range"))
        return FakeResponse(
            [b"cd", b""],
            status=206,
            headers={"Content-Range": "bytes 2-3/4"},
        )

    monkeypatch.setattr(whisper_models.urllib.request, "urlopen", fake_urlopen)

    path = manager.download_model("medium", lambda done, total: progress.append((done, total)))

    assert seen_range == ["bytes=2-"]
    assert path.read_bytes() == b"abcd"
    assert progress[0] == (2, 4)
    assert progress[-1] == (4, 4)


def test_delete_model_removes_model_hash_and_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _small_medium(monkeypatch)
    manager = WhisperModelManager(tmp_path)
    target = tmp_path / "ggml-medium.bin"
    target.write_bytes(b"abcd")
    manager._sha_path(target).write_text("hash\n", encoding="ascii")
    target.with_name(target.name + ".part").write_bytes(b"partial")

    assert manager.delete_model("medium") is True
    assert not target.exists()
    assert not manager._sha_path(target).exists()
    assert not target.with_name(target.name + ".part").exists()
    assert manager.delete_model("medium") is False


def test_unknown_model_is_rejected(tmp_path: Path) -> None:
    manager = WhisperModelManager(tmp_path)
    with pytest.raises(ValueError):
        manager.get_model_info("../../evil")
    with pytest.raises(ValueError):
        manager.get_model_path("../../evil")
    with pytest.raises(ValueError):
        manager.is_model_cached("../../evil")
    with pytest.raises(ValueError):
        manager.download_model("../../evil", lambda _done, _total: None)
    with pytest.raises(ValueError):
        manager.delete_model("../../evil")
