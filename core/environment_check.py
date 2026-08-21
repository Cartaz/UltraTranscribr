"""Headless environment diagnostics for UltraTranscribr."""
from __future__ import annotations

import importlib.util
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from config.constants import AppMeta, ProcessDefaults, WhisperServerDefaults
from core.whisper_gpu_detect import (
    _check_compute_runtime,
    _check_intel_gpu,
    _check_level_zero_loader,
    find_whisper_server,
    verify_sycl_binary,
)
from core.whisper_models import WhisperModelManager


@dataclass(frozen=True)
class EnvironmentCheck:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def collect_environment_checks(project_root: Path | None = None) -> list[EnvironmentCheck]:
    """Return cheap, non-destructive checks for the supported runtime."""
    root = Path(project_root or Path(__file__).resolve().parent.parent)
    manager = WhisperModelManager()

    server = find_whisper_server(root)
    server_ok = bool(server and verify_sycl_binary(server, root))

    default_model = manager.get_model_info(ProcessDefaults.MODEL_SIZE)
    vad_path = AppMeta.MODELS_DIR / WhisperServerDefaults.VAD_MODEL_FILENAME
    try:
        vad_ok = vad_path.is_file() and vad_path.stat().st_size >= 100_000
    except OSError:
        vad_ok = False

    checks = [
        EnvironmentCheck(
            "Python 3.11+",
            sys.version_info >= (3, 11),
            sys.version.split()[0],
        ),
        EnvironmentCheck(
            "Intel oneAPI",
            Path("/opt/intel/oneapi/setvars.sh").is_file(),
            "/opt/intel/oneapi/setvars.sh",
        ),
        EnvironmentCheck(
            "Level Zero loader",
            _check_level_zero_loader(),
            "libze_loader",
        ),
        EnvironmentCheck(
            "Intel Compute Runtime",
            _check_compute_runtime(),
            "Level Zero Intel GPU runtime",
        ),
        EnvironmentCheck(
            "Intel GPU",
            _check_intel_gpu(),
            "Intel VGA / Display / 3D controller",
        ),
        EnvironmentCheck(
            "ffmpeg",
            shutil.which("ffmpeg") is not None,
            shutil.which("ffmpeg") or "non trovato",
        ),
        EnvironmentCheck(
            "whisper-server SYCL",
            server_ok,
            server or "non trovato",
        ),
        EnvironmentCheck(
            f"Modello ASR {ProcessDefaults.MODEL_SIZE}",
            bool(default_model.get("installed")),
            str(default_model.get("path") or "non trovato"),
        ),
        EnvironmentCheck(
            "Modello VAD",
            vad_ok,
            str(vad_path),
        ),
    ]

    for module in ("PySide6", "numpy", "sounddevice", "soundfile", "pulsectl", "huggingface_hub"):
        checks.append(
            EnvironmentCheck(
                f"Python package {module}",
                _module_available(module),
                "installato" if _module_available(module) else "non trovato",
            )
        )

    demucs_ok = _module_available("demucs") and _module_available("torch")
    checks.append(
        EnvironmentCheck(
            "Demucs (opzionale)",
            demucs_ok,
            "disponibile" if demucs_ok else "non installato",
            required=False,
        )
    )
    return checks


def required_checks_pass(checks: Iterable[EnvironmentCheck]) -> bool:
    return all(check.ok for check in checks if check.required)


def format_environment_report(checks: Iterable[EnvironmentCheck]) -> str:
    lines = ["=== UltraTranscribr environment check ==="]
    for check in checks:
        if check.ok:
            marker = "OK"
        elif check.required:
            marker = "FAIL"
        else:
            marker = "OPTIONAL"
        lines.append(f"[{marker:8}] {check.name}: {check.detail}")
    return "\n".join(lines)


def main() -> int:
    checks = collect_environment_checks()
    print(format_environment_report(checks))
    return 0 if required_checks_pass(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
