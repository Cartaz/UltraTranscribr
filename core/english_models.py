"""Pinned local assets for the optional English meeting pipeline."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from collections.abc import Callable
from pathlib import Path
from threading import Event

from config.constants import AppMeta


class EnglishPipelineCancelled(RuntimeError):
    """The optional pipeline was cancelled by its owning meeting job."""


class EnglishModelManager:
    def __init__(self, root: Path | None = None, *, manifest_path: Path | None = None):
        self.root = root or AppMeta.CACHE_DIR / "models" / "english"
        manifest_path = (
            manifest_path
            or Path(__file__).resolve().parents[1] / "config" / "english-models.json"
        )
        self.manifest = json.loads(manifest_path.read_text())
        self.models = {item["name"]: item for item in self.manifest["models"]}

    def path(self, name: str) -> Path:
        if name not in self.models:
            raise ValueError("Unknown English pipeline model")
        return self.root / self.models[name].get("directory", name)

    def dependencies(self) -> dict[str, str]:
        """Inspect package versions without loading a model or touching the GPU."""
        versions = {}
        for package in ("torch", "transformers", "soundfile", "pyannote.audio"):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError as exc:
                raise RuntimeError(
                    "I componenti delle riunioni non sono disponibili in questa installazione. Aggiorna il programma."
                ) from exc
        if versions["transformers"] != self.manifest["transformers_version"]:
            raise RuntimeError(
                "Aggiorna i componenti del programma per attivare il motore riunioni."
            )
        if "+xpu" not in versions["torch"]:
            raise RuntimeError(
                "Il motore riunioni richiede il runtime Intel XPU dell'app."
            )
        if versions["pyannote.audio"] != self.manifest["pyannote_version"]:
            raise RuntimeError(
                "Il motore riunioni richiede la versione verificata del componente voci."
            )
        return versions

    def missing(self) -> list[str]:
        return [
            name
            for name, model in self.models.items()
            if any(
                not (self.path(name) / item["name"]).is_file()
                or (self.path(name) / item["name"]).stat().st_size != item["bytes"]
                for item in model["files"]
            )
        ]

    def verify(
        self,
        *,
        cancel: Event | None = None,
        progress: Callable[[int], None] | None = None,
        names: list[str] | None = None,
    ) -> dict[str, str]:
        """Verify the exact assets used in the validated public pipeline."""
        hashes = {}
        selected = (
            {name: self.models[name] for name in names}
            if names is not None
            else self.models
        )
        total = sum(
            item["bytes"] for model in selected.values() for item in model["files"]
        )
        processed = 0
        for name, model in selected.items():
            for item in model["files"]:
                if cancel and cancel.is_set():
                    raise EnglishPipelineCancelled()
                path = self.path(name) / item["name"]
                digest = hashlib.sha256()
                try:
                    with path.open("rb") as stream:
                        while block := stream.read(2 * 1024 * 1024):
                            if cancel and cancel.is_set():
                                raise EnglishPipelineCancelled()
                            digest.update(block)
                            processed += len(block)
                            if progress:
                                progress(min(100, int(100 * processed / max(total, 1))))
                except FileNotFoundError as exc:
                    raise RuntimeError("Mancano modelli del motore riunioni.") from exc
                actual = digest.hexdigest()
                if actual != item["sha256"] or path.stat().st_size != item["bytes"]:
                    raise RuntimeError(
                        "Un modello del motore riunioni è incompleto o diverso dalla versione verificata."
                    )
                hashes[f"{name}/{item['name']}"] = actual
        return hashes

    def download(
        self, *, cancel: Event, progress: Callable[[int], None] | None = None
    ) -> None:
        """Run in the owning worker process so cancellation can stop a download.

        Hugging Face manages partial files; strong verification precedes model use.
        The parent job must terminate the worker for cancellation within a file.
        """
        from huggingface_hub import hf_hub_download

        files = [
            (name, model, item)
            for name, model in self.models.items()
            for item in model["files"]
        ]
        for index, (name, model, item) in enumerate(files):
            if cancel.is_set():
                raise EnglishPipelineCancelled()
            path = self.path(name) / item["name"]
            valid = False
            if path.is_file() and path.stat().st_size == item["bytes"]:
                with path.open("rb") as stream:
                    valid = (
                        hashlib.file_digest(stream, "sha256").hexdigest()
                        == item["sha256"]
                    )
            if not valid:
                try:
                    hf_hub_download(
                        repo_id=model["repository"],
                        revision=model["revision"],
                        filename=item["name"],
                        local_dir=self.path(name),
                        force_download=path.exists(),
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "Download dei modelli non riuscito: verifica connessione e accesso a Community-1 su Hugging Face."
                    ) from exc
            if progress:
                progress(int(100 * (index + 1) / len(files)))
        self.verify(cancel=cancel)
        if "community3" in self.models:
            model = self.models["community3"]
            marker = self.path("community3") / ".ultratranscribr-model.json"
            expected = {"repo_id": model["repository"], "revision": model["revision"]}
            if marker.exists():
                try:
                    if json.loads(marker.read_text()) == expected:
                        return
                except (OSError, ValueError):
                    pass
            temporary = marker.with_suffix(".tmp")
            temporary.write_text(json.dumps(expected))
            temporary.replace(marker)
