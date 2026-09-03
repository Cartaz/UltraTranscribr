from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core import sycl_runtime


def test_oneapi_library_probe_starts_clean_and_forces_reinitialization(monkeypatch) -> None:
    sycl_runtime.oneapi_library_paths.cache_clear()
    monkeypatch.setattr(sycl_runtime._ONEAPI_SETVARS, "is_file", lambda: True)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/venv/old-runtime:/custom")
    monkeypatch.setenv("SETVARS_COMPLETED", "1")
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        return SimpleNamespace(
            returncode=0,
            stdout="/opt/intel/oneapi/compiler/2026.0/lib:/opt/intel/oneapi/tbb/2022/lib",
            stderr="",
        )

    monkeypatch.setattr(sycl_runtime.subprocess, "run", fake_run)

    assert sycl_runtime.oneapi_library_paths() == (
        "/opt/intel/oneapi/compiler/2026.0/lib",
        "/opt/intel/oneapi/tbb/2022/lib",
    )
    assert "LD_LIBRARY_PATH" not in captured["env"]
    command = captured["cmd"]
    assert isinstance(command, list)
    assert 'SETVARS_ARGS="--force"' in command[2]
    sycl_runtime.oneapi_library_paths.cache_clear()


def test_whisper_env_prioritizes_oneapi_before_virtualenv_runtime(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / "lib").mkdir()
    monkeypatch.setattr(
        sycl_runtime,
        "oneapi_library_paths",
        lambda: (
            "/opt/intel/oneapi/compiler/2026.0/lib",
            "/opt/intel/oneapi/tbb/2022/lib",
        ),
    )

    env = sycl_runtime.build_whisper_sycl_env(
        tmp_path,
        base_env={"LD_LIBRARY_PATH": "/legacy/lib", "KEEP_ME": "yes"},
    )

    paths = env["LD_LIBRARY_PATH"].split(":")
    assert paths[:2] == [
        "/opt/intel/oneapi/compiler/2026.0/lib",
        "/opt/intel/oneapi/tbb/2022/lib",
    ]
    assert paths[2:4] == [str(tmp_path / ".venv" / "lib"), str(tmp_path / "lib")]
    assert paths[-1] == "/legacy/lib"
    assert env["KEEP_ME"] == "yes"
    assert env["GGML_SYCL"] == "1"
    assert env["ONEAPI_DEVICE_SELECTOR"] == "level_zero:0"


def test_oneapi_probe_failure_is_actionable(monkeypatch) -> None:
    sycl_runtime.oneapi_library_paths.cache_clear()
    monkeypatch.setattr(sycl_runtime._ONEAPI_SETVARS, "is_file", lambda: True)
    monkeypatch.setattr(
        sycl_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=2, stdout="", stderr="bad vars"),
    )

    with pytest.raises(RuntimeError, match="bad vars"):
        sycl_runtime.oneapi_library_paths()
    sycl_runtime.oneapi_library_paths.cache_clear()
