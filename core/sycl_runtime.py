"""Runtime environment construction for whisper.cpp SYCL subprocesses.

The Python process also hosts PyTorch XPU.  Those two consumers can depend on
slightly different Intel runtime releases, so whisper-server must receive the
oneAPI environment in its own subprocess instead of mutating the application
process environment.
"""
from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from config.constants import SYCLDefaults

_ONEAPI_ROOT = Path("/opt/intel/oneapi")
_ONEAPI_SETVARS = _ONEAPI_ROOT / "setvars.sh"


def _split_paths(value: str) -> list[str]:
    return [item for item in value.split(":") if item]


def _dedupe(paths: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


@lru_cache(maxsize=1)
def oneapi_library_paths() -> tuple[str, ...]:
    """Return Intel's own runtime library order from ``setvars.sh``.

    ``LD_LIBRARY_PATH`` is deliberately removed from the probe environment so
    a virtualenv-provided Unified Runtime cannot be folded into the oneAPI
    result and then outrank the compiler runtime that built whisper.cpp.
    """

    if not _ONEAPI_SETVARS.is_file():
        raise RuntimeError(f"Intel oneAPI non trovato: {_ONEAPI_SETVARS}")

    env = os.environ.copy()
    env.pop("LD_LIBRARY_PATH", None)
    command = (
        'source "$1" >/dev/null 2>&1 '
        '&& printf "%s" "${LD_LIBRARY_PATH:-}"'
    )
    try:
        completed = subprocess.run(
            ["bash", "-c", command, "ultratranscribr-oneapi", str(_ONEAPI_SETVARS)],
            env=env,
            capture_output=True,
            text=True,
            timeout=15.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Impossibile inizializzare Intel oneAPI: {exc}") from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise RuntimeError(f"Intel oneAPI setvars.sh fallito: {detail}")

    paths = tuple(_dedupe(_split_paths(completed.stdout.strip())))
    if not paths:
        raise RuntimeError("Intel oneAPI non ha prodotto LD_LIBRARY_PATH")
    return paths


def build_whisper_sycl_env(
    project_root: Path,
    *,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build an isolated environment for one whisper.cpp SYCL process.

    oneAPI paths must precede ``.venv/lib``.  PyTorch XPU installs its own
    Unified Runtime in the virtualenv; putting that directory first can mix a
    newer oneAPI ``libsycl`` with an older ``libur_loader`` and abort the
    server at dynamic-link time.
    """

    env = dict(os.environ if base_env is None else base_env)
    app_paths = [
        str(path)
        for path in (Path(project_root) / ".venv" / "lib", Path(project_root) / "lib")
        if path.is_dir()
    ]
    inherited = _split_paths(env.get("LD_LIBRARY_PATH", ""))
    runtime_paths = list(oneapi_library_paths())
    env["LD_LIBRARY_PATH"] = ":".join(_dedupe(runtime_paths + app_paths + inherited))
    env["GGML_SYCL"] = "1"
    env["ONEAPI_DEVICE_SELECTOR"] = SYCLDefaults.ONEAPI_DEVICE_SELECTOR
    env["ZES_ENABLE_SYSMAN"] = "1"
    return env
