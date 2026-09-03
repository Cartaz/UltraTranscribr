"""Intel SYCL backend detection."""
from __future__ import annotations

import ctypes.util
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from config.constants import WhisperServerDefaults
from core.sycl_runtime import build_whisper_sycl_env

logger = logging.getLogger(__name__)


def find_whisper_server(project_root: Optional[Path] = None) -> Optional[str]:
    root = project_root or Path(__file__).resolve().parent.parent
    for path in (
        root / ".venv/bin" / WhisperServerDefaults.SERVER_BINARY_NAME,
        root / WhisperServerDefaults.SERVER_BINARY_NAME,
        root / "libexec" / WhisperServerDefaults.SERVER_BINARY_NAME,
    ):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return shutil.which(WhisperServerDefaults.SERVER_BINARY_NAME)


def _check_level_zero_loader() -> bool:
    if ctypes.util.find_library("ze_loader"):
        return True
    return any(
        any(Path(path).glob("libze_loader.so*"))
        for path in ("/usr/lib", "/usr/lib64", "/usr/local/lib")
    )


def _check_intel_gpu() -> bool:
    try:
        output = subprocess.run(
            ["lspci", "-nn"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.lower()
        return "intel" in output and any(
            token in output for token in ("vga", "display", "3d controller")
        )
    except (OSError, subprocess.TimeoutExpired):
        return bool(shutil.which("sycl-ls") or shutil.which("clinfo"))


def _check_compute_runtime() -> bool:
    if shutil.which("sycl-ls") or shutil.which("clinfo"):
        return True
    return Path("/usr/lib/libze_intel_gpu.so").exists() or any(
        Path("/usr/lib").glob("libze_intel_gpu.so*")
    )


def is_sycl_available(project_root: Optional[Path] = None) -> bool:
    del project_root
    checks = (_check_level_zero_loader(), _check_compute_runtime(), _check_intel_gpu())
    logger.info("SYCL checks: LevelZero=%s runtime=%s IntelGPU=%s", *checks)
    return all(checks)


def detect_gpu_backend(project_root: Optional[Path] = None) -> str:
    return "sycl" if is_sycl_available(project_root) else "unavailable"


def verify_sycl_binary(binary_path: str, project_root: Optional[Path] = None) -> bool:
    """Verify that whisper-server is SYCL-linked and starts with a coherent runtime."""

    root = project_root or Path(__file__).resolve().parent.parent
    try:
        env = build_whisper_sycl_env(root)
    except RuntimeError as exc:
        logger.error("Ambiente oneAPI non valido per whisper-server: %s", exc)
        return False

    try:
        linked = subprocess.run(
            ["ldd", binary_path],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.error("Impossibile verificare linkage whisper-server: %s", exc)
        return False

    linkage = (linked.stdout + linked.stderr).lower()
    if not any(token in linkage for token in ("libggml-sycl", "libsycl")):
        return False

    try:
        probe = subprocess.run(
            [binary_path, "--help"],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.error("Avvio di prova whisper-server fallito: %s", exc)
        return False

    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip()[-1200:]
        logger.error("whisper-server SYCL non avviabile: %s", detail or probe.returncode)
        return False
    return True
