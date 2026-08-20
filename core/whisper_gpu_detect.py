# core/whisper_gpu_detect.py
"""Rilevamento GPU Intel Arc e supporto SYCL per whisper-server.

Verifica la presenza di driver Level Zero, Intel Compute Runtime
e GPU Intel Arc necessari per l'accelerazione SYCL. La logica
segue lo stesso approccio del progetto GLM-OCR Desktop, con
ricerca del binary whisper-server compilato con SYCL e verifica
delle librerie condivise.

La priorita di ricerca del binary e:
  1. .venv/bin/whisper-server (SYCL, immune da pacman)
  2. ./whisper-server (directory progetto)
  3. Sistema PATH (pacman/AUR, potrebbe essere CPU-only)

Functions:
    find_whisper_server: Trova il binary whisper-server.
    is_sycl_available: Verifica se SYCL e disponibile sul sistema.
    detect_gpu_backend: Rileva il backend GPU ottimale.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from config.constants import WhisperServerDefaults

logger = logging.getLogger(__name__)


def find_whisper_server(project_root: Optional[Path] = None) -> Optional[str]:
    """Trova il binary whisper-server con priorita SYCL.

    La ricerca segue la priorita descritta nella documentazione:
    venv → directory progetto → sistema PATH. Il binary nel venv
    e compilato con SYCL e protetto da aggiornamenti pacman.

    Args:
        project_root: Directory radice del progetto. Se None,
            usa la directory del modulo corrente.

    Returns:
        Percorso del binary whisper-server, oppure None se non trovato.
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    candidates = [
        project_root / ".venv" / "bin" / WhisperServerDefaults.SERVER_BINARY_NAME,
        project_root / WhisperServerDefaults.SERVER_BINARY_NAME,
    ]

    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            logger.info("whisper-server trovato: %s", candidate)
            return str(candidate)

    # Fallback: cerca nel PATH di sistema
    import shutil
    system_binary = shutil.which(WhisperServerDefaults.SERVER_BINARY_NAME)
    if system_binary:
        logger.info("whisper-server trovato nel PATH: %s", system_binary)
        return system_binary

    logger.warning("whisper-server non trovato in nessuna posizione")
    return None


def is_sycl_available(project_root: Optional[Path] = None) -> bool:
    """Verifica se il supporto SYCL e disponibile sul sistema.

    Controlla tre condizioni come descritto nel report di implementazione
    OCR: esistenza di libze_loader.so, presenza del comando ocloc,
    e rilevamento di una GPU Intel tramite lspci. Tutte e tre le
    condizioni devono essere soddisfatte simultaneamente.

    Args:
        project_root: Directory radice del progetto per la ricerca del venv.

    Returns:
        True se SYCL e disponibile, False altrimenti.
    """
    checks = [
        _check_level_zero_loader(),
        _check_intel_compute_runtime(),
        _check_intel_gpu(),
    ]

    all_passed = all(checks)
    if all_passed:
        logger.info("Supporto SYCL GPU Intel Arc: disponibile")
    else:
        logger.warning(
            "Supporto SYCL non disponibile — "
            "Level Zero: %s, Compute Runtime: %s, GPU Intel: %s",
            checks[0], checks[1], checks[2],
        )
    return all_passed


def detect_gpu_backend(project_root: Optional[Path] = None) -> str:
    """Rileva il backend GPU ottimale per whisper-server.

    Restituisce sempre "sycl" se disponibile. Non vengono offerti
    fallback a CPU o altri backend, conforme al requisito utente
    di solo accelerazione GPU.

    Args:
        project_root: Directory radice del progetto.

    Returns:
        "sycl" se SYCL e disponibile, altrimenti "unavailable".
    """
    if is_sycl_available(project_root):
        return "sycl"
    return "unavailable"


def verify_sycl_binary(binary_path: str, project_root: Optional[Path] = None) -> bool:
    """Verifica che il binary whisper-server sia compilato con SYCL.

    Utilizza tre metodi in cascata come nel progetto OCR:
    1. --version controlla se il compilatore riportato e IntelLLVM
    2. ldd verifica la presenza di librerie SYCL tra le dipendenze
    3. --help cerca la stringa "sycl" nell'output

    Args:
        binary_path: Percorso del binary whisper-server.
        project_root: Directory radice del progetto per LD_LIBRARY_PATH.

    Returns:
        True se il binary supporta SYCL, False altrimenti.
    """
    env = _venv_lib_env(project_root)

    # Metodo 1: --version con compilatore IntelLLVM
    if _check_version_sycl(binary_path, env):
        logger.info("SYCL verificato via --version (IntelLLVM)")
        return True

    # Metodo 2: ldd per librerie SYCL
    if _check_ldd_sycl(binary_path, env):
        logger.info("SYCL verificato via ldd")
        return True

    # Metodo 3: --help con stringa "sycl"
    if _check_help_sycl(binary_path, env):
        logger.info("SYCL verificato via --help")
        return True

    logger.warning("Nessuna evidenza SYCL nel binary: %s", binary_path)
    return False


def _venv_lib_env(project_root: Optional[Path] = None) -> dict[str, str]:
    """Costruisce l'ambiente con LD_LIBRARY_PATH per il venv.

    Senza LD_LIBRARY_PATH, il binary SYCL nel venv non puo
    trovare le librerie condivise, causando exit code 127.

    Args:
        project_root: Directory radice del progetto.

    Returns:
        Copia dell'ambiente con LD_LIBRARY_PATH aggiornato.
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    env = os.environ.copy()

    ld_paths: list[str] = []
    venv_lib = project_root / ".venv" / "lib"
    if venv_lib.exists():
        ld_paths.append(str(venv_lib))

    # Aggiungi librerie oneAPI per verifica SYCL
    oneapi_root = Path("/opt/intel/oneapi")
    if oneapi_root.exists():
        for component_dir in oneapi_root.iterdir():
            if not component_dir.is_dir():
                continue
            for vdir in (sorted(component_dir.iterdir()) if component_dir.is_dir() else []):
                lib_dir = vdir / "lib"
                if lib_dir.is_dir():
                    ld_paths.append(str(lib_dir))
                tbb_lib = vdir / "lib" / "intel64" / "gcc4.8"
                if tbb_lib.is_dir():
                    ld_paths.append(str(tbb_lib))

    current_ld = env.get("LD_LIBRARY_PATH", "")
    if ld_paths:
        new_ld = ":".join(ld_paths)
        env["LD_LIBRARY_PATH"] = f"{new_ld}:{current_ld}" if current_ld else new_ld
    return env


def _check_level_zero_loader() -> bool:
    """Verifica l'esistenza di libze_loader.so."""
    search_paths = [Path("/usr/lib"), Path("/usr/lib64"), Path("/usr/local/lib")]
    for path in search_paths:
        if list(path.glob("libze_loader.so*")):
            return True
    return False


def _check_intel_compute_runtime() -> bool:
    """Verifica la presenza del comando ocloc (Intel Compute Runtime)."""
    import shutil
    return shutil.which("ocloc") is not None


def _check_intel_gpu() -> bool:
    """Verifica la presenza di una GPU Intel tramite lspci."""
    try:
        result = subprocess.run(
            ["lspci"], capture_output=True, text=True, timeout=5,
        )
        return "VGA compatible controller: Intel" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _check_version_sycl(binary_path: str, env: dict[str, str]) -> bool:
    """Verifica SYCL tramite --version (compilatore IntelLLVM)."""
    try:
        result = subprocess.run(
            [binary_path, "--version"],
            capture_output=True, text=True, timeout=10, env=env,
        )
        output = result.stdout + result.stderr
        return "IntelLLVM" in output or "icx" in output
    except (subprocess.TimeoutExpired, OSError):
        return False


def _check_ldd_sycl(binary_path: str, env: dict[str, str]) -> bool:
    """Verifica SYCL tramite ldd (librerie collegate)."""
    try:
        result = subprocess.run(
            ["ldd", binary_path],
            capture_output=True, text=True, timeout=10, env=env,
        )
        output = result.stdout
        sycl_indicators = ["libsycl", "libze_loader", "libggml-sycl"]
        return any(ind in output for ind in sycl_indicators)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _check_help_sycl(binary_path: str, env: dict[str, str]) -> bool:
    """Verifica SYCL tramite --help (stringa "sycl" o "level-zero")."""
    try:
        result = subprocess.run(
            [binary_path, "--help"],
            capture_output=True, text=True, timeout=10, env=env,
        )
        output = (result.stdout + result.stderr).lower()
        return "sycl" in output or "level-zero" in output
    except (subprocess.TimeoutExpired, OSError):
        return False
