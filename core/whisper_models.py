"""Download e cache verificabile dei modelli Whisper/VAD."""
from __future__ import annotations

import hashlib
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from config.constants import AppMeta, WhisperServerDefaults

logger = logging.getLogger(__name__)

_ASR_REPOS = [
    WhisperServerDefaults.MODEL_REPO_ID,
    WhisperServerDefaults.MODEL_REPO_FALLBACK,
]
_VAD_REPOS = [WhisperServerDefaults.VAD_REPO_ID]

_MODEL_FILES = {
    "tiny": "ggml-tiny.bin",
    "tiny.en": "ggml-tiny.en.bin",
    "base": "ggml-base.bin",
    "base.en": "ggml-base.en.bin",
    "small": "ggml-small.bin",
    "small.en": "ggml-small.en.bin",
    "medium": "ggml-medium.bin",
    "medium.en": "ggml-medium.en.bin",
    "large-v3": "ggml-large-v3.bin",
    "large-v3-turbo": "ggml-large-v3-turbo.bin",
}
_MIN_MODEL_BYTES = {
    "tiny": 50_000_000, "tiny.en": 50_000_000,
    "base": 100_000_000, "base.en": 100_000_000,
    "small": 300_000_000, "small.en": 300_000_000,
    "medium": 900_000_000, "medium.en": 900_000_000,
    "large-v3": 1_000_000_000, "large-v3-turbo": 500_000_000,
}
_UI_MODEL_CHOICES = ("large-v3", "large-v3-turbo", "medium")
ProgressCallback = Callable[[int, Optional[int]], None]


class WhisperModelManager:
    def __init__(self, models_dir: Optional[Path] = None) -> None:
        self._models_dir = models_dir or AppMeta.MODELS_DIR

    @property
    def models_dir(self) -> Path:
        return self._models_dir

    @staticmethod
    def ui_model_choices() -> tuple[str, ...]:
        return _UI_MODEL_CHOICES

    def get_model_path(self, model_size: str) -> Path:
        filename = self._resolve_filename(model_size)
        target = self._models_dir / filename
        min_bytes = _MIN_MODEL_BYTES.get(model_size, 1_000_000)
        if self._is_valid_cached(target, min_bytes):
            return target
        return self._download_asset(_ASR_REPOS, filename, target, min_bytes)

    def get_vad_model_path(self) -> Path:
        filename = WhisperServerDefaults.VAD_MODEL_FILENAME
        target = self._models_dir / filename
        if self._is_valid_cached(target, 100_000):
            return target
        return self._download_asset(_VAD_REPOS, filename, target, 100_000)

    def is_model_cached(self, model_size: str) -> bool:
        target = self._models_dir / self._resolve_filename(model_size)
        return self._is_valid_cached(target, _MIN_MODEL_BYTES.get(model_size, 1_000_000))

    def get_model_info(self, model_size: str) -> dict[str, object]:
        """Return cheap inventory information without hashing multi-GB files."""
        self._require_known_model(model_size)
        target = self._models_dir / self._resolve_filename(model_size)
        part = target.with_name(target.name + ".part")
        min_bytes = _MIN_MODEL_BYTES[model_size]
        try:
            size_bytes = target.stat().st_size if target.is_file() else 0
        except OSError:
            size_bytes = 0
        try:
            partial_bytes = part.stat().st_size if part.is_file() else 0
        except OSError:
            partial_bytes = 0
        sha_path = self._sha_path(target)
        installed = size_bytes >= min_bytes
        return {
            "model": model_size,
            "filename": target.name,
            "path": str(target),
            "installed": installed,
            "size_bytes": size_bytes,
            "partial_bytes": partial_bytes,
            "min_bytes": min_bytes,
            "verified": bool(installed and sha_path.is_file()),
        }

    def list_ui_models(self) -> list[dict[str, object]]:
        return [self.get_model_info(model) for model in _UI_MODEL_CHOICES]

    def download_model(
        self,
        model_size: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Path:
        """Download a known ASR model, preferring resumable HTTP for UI progress."""
        self._require_known_model(model_size)
        filename = self._resolve_filename(model_size)
        target = self._models_dir / filename
        min_bytes = _MIN_MODEL_BYTES[model_size]
        if self._is_valid_cached(target, min_bytes):
            size = target.stat().st_size
            self._notify_progress(progress_callback, size, size)
            return target
        if progress_callback is None:
            return self._download_asset(_ASR_REPOS, filename, target, min_bytes)

        self._models_dir.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []
        for repo in _ASR_REPOS:
            url = f"https://huggingface.co/{repo}/resolve/main/{filename}"
            try:
                result = self._download_with_progress(
                    url, target, min_bytes, progress_callback=progress_callback
                )
                if result is not None:
                    return result
            except Exception as exc:
                errors.append(f"HTTP {url}: {exc}")
        details = "\n".join(f"  - {e}" for e in errors[-8:])
        raise RuntimeError(
            f"Download modello fallito ({filename}).\n{details}\n"
            f"Scaricalo manualmente in {target}"
        )

    def delete_model(self, model_size: str) -> bool:
        """Delete only files belonging to a known model inside models_dir."""
        self._require_known_model(model_size)
        target = self._models_dir / self._resolve_filename(model_size)
        removed = False
        for path in (
            target,
            self._sha_path(target),
            target.with_name(target.name + ".part"),
        ):
            try:
                if path.is_file():
                    path.unlink()
                    removed = True
            except OSError as exc:
                raise RuntimeError(f"Impossibile eliminare {path}: {exc}") from exc
        return removed

    def _resolve_filename(self, model_size: str) -> str:
        return _MODEL_FILES.get(model_size, WhisperServerDefaults.MODEL_FILENAME)

    @staticmethod
    def _require_known_model(model_size: str) -> None:
        if model_size not in _MODEL_FILES:
            raise ValueError(f"modello non valido: {model_size}")

    @staticmethod
    def _sha_path(target: Path) -> Path:
        return target.with_name(target.name + ".sha256")

    def _is_valid_cached(self, target: Path, min_bytes: int) -> bool:
        try:
            if not target.is_file() or target.stat().st_size < min_bytes:
                return False
            sha_path = self._sha_path(target)
            if sha_path.is_file():
                expected = sha_path.read_text(encoding="ascii").strip().split()[0]
                actual = self._sha256(target)
                if actual != expected:
                    logger.warning("Hash cache non valido per %s; riscarico", target)
                    return False
            return True
        except OSError:
            return False

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()

    def _write_hash(self, target: Path) -> None:
        digest = self._sha256(target)
        tmp = self._sha_path(target).with_suffix(self._sha_path(target).suffix + ".tmp")
        tmp.write_text(digest + "\n", encoding="ascii")
        os.replace(tmp, self._sha_path(target))

    def _download_asset(self, repos: list[str], filename: str, target: Path,
                        min_bytes: int) -> Path:
        self._models_dir.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []

        try:
            from huggingface_hub import hf_hub_download
        except ImportError:
            hf_hub_download = None

        if hf_hub_download is not None:
            for repo in repos:
                try:
                    path = Path(hf_hub_download(
                        repo_id=repo, filename=filename, local_dir=str(self._models_dir)
                    ))
                    if path != target:
                        import shutil
                        shutil.copy2(path, target)
                    if target.stat().st_size < min_bytes:
                        raise RuntimeError("file scaricato troppo piccolo")
                    self._write_hash(target)
                    logger.info("Modello scaricato da %s: %s", repo, target)
                    return target
                except Exception as exc:
                    errors.append(f"huggingface-hub {repo}/{filename}: {exc}")

        for repo in repos:
            url = f"https://huggingface.co/{repo}/resolve/main/{filename}"
            try:
                result = self._download_with_progress(url, target, min_bytes)
                if result is not None:
                    return result
            except Exception as exc:
                errors.append(f"HTTP {url}: {exc}")

        details = "\n".join(f"  - {e}" for e in errors[-8:])
        raise RuntimeError(
            f"Download modello fallito ({filename}).\n{details}\n"
            f"Scaricalo manualmente in {target}"
        )

    def _download_with_progress(
        self,
        url: str,
        target: Path,
        min_bytes: int,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Optional[Path]:
        part = target.with_name(target.name + ".part")
        existing = part.stat().st_size if part.exists() else 0
        req = urllib.request.Request(url)
        if existing:
            req.add_header("Range", f"bytes={existing}-")
        with urllib.request.urlopen(req, timeout=30) as resp:
            partial = resp.status == 206 and existing > 0
            mode = "ab" if partial else "wb"
            if not partial:
                existing = 0
            expected_total: Optional[int] = None
            content_range = resp.headers.get("Content-Range")
            if content_range and "/" in content_range:
                tail = content_range.rsplit("/", 1)[-1]
                if tail.isdigit():
                    expected_total = int(tail)
            if expected_total is None:
                content_length = resp.headers.get("Content-Length")
                if content_length and content_length.isdigit():
                    expected_total = existing + int(content_length)

            downloaded = existing
            self._notify_progress(progress_callback, downloaded, expected_total)
            with part.open(mode) as f:
                while True:
                    block = resp.read(1024 * 1024)
                    if not block:
                        break
                    f.write(block)
                    downloaded += len(block)
                    self._notify_progress(progress_callback, downloaded, expected_total)

        actual = part.stat().st_size if part.exists() else 0
        if expected_total is not None and actual != expected_total:
            raise RuntimeError(f"download troncato: {actual}/{expected_total} byte")
        if actual < min_bytes:
            raise RuntimeError(f"file troppo piccolo: {actual} byte")
        os.replace(part, target)
        self._write_hash(target)
        self._notify_progress(progress_callback, actual, actual)
        logger.info("Download completato: %s (%.1f MiB)", target, actual / 1048576)
        return target

    @staticmethod
    def _notify_progress(
        callback: Optional[ProgressCallback],
        downloaded: int,
        total: Optional[int],
    ) -> None:
        if callback is None:
            return
        try:
            callback(int(downloaded), int(total) if total is not None else None)
        except Exception:
            logger.debug("Callback progresso modello fallita", exc_info=True)
