from __future__ import annotations

from pathlib import Path

import core.environment_check as envcheck


def test_optional_failures_do_not_fail_environment() -> None:
    checks = [
        envcheck.EnvironmentCheck("required", True, "ok"),
        envcheck.EnvironmentCheck("optional", False, "missing", required=False),
    ]
    assert envcheck.required_checks_pass(checks) is True


def test_required_failure_fails_environment() -> None:
    checks = [
        envcheck.EnvironmentCheck("required", False, "missing"),
        envcheck.EnvironmentCheck("optional", True, "ok", required=False),
    ]
    assert envcheck.required_checks_pass(checks) is False


def test_report_distinguishes_required_and_optional_failures() -> None:
    report = envcheck.format_environment_report(
        [
            envcheck.EnvironmentCheck("good", True, "ready"),
            envcheck.EnvironmentCheck("bad", False, "missing"),
            envcheck.EnvironmentCheck("extra", False, "not installed", required=False),
        ]
    )
    assert "[OK      ] good: ready" in report
    assert "[FAIL    ] bad: missing" in report
    assert "[OPTIONAL] extra: not installed" in report


def test_collect_environment_checks_is_non_destructive(monkeypatch, tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    vad_path = models_dir / envcheck.WhisperServerDefaults.VAD_MODEL_FILENAME
    vad_path.write_bytes(b"x" * 100_000)

    monkeypatch.setattr(envcheck.AppMeta, "MODELS_DIR", models_dir)
    monkeypatch.setattr(envcheck, "_check_level_zero_loader", lambda: True)
    monkeypatch.setattr(envcheck, "_check_compute_runtime", lambda: True)
    monkeypatch.setattr(envcheck, "_check_intel_gpu", lambda: True)
    monkeypatch.setattr(envcheck, "find_whisper_server", lambda root: "/tmp/whisper-server")
    monkeypatch.setattr(envcheck, "verify_sycl_binary", lambda binary, root: True)
    monkeypatch.setattr(envcheck.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(envcheck, "_module_available", lambda name: name not in {"demucs", "torch"})

    class FakeManager:
        def get_model_info(self, model: str) -> dict[str, object]:
            assert model == envcheck.ProcessDefaults.MODEL_SIZE
            return {
                "installed": True,
                "path": str(models_dir / "ggml-large-v3-turbo.bin"),
            }

    monkeypatch.setattr(envcheck, "WhisperModelManager", FakeManager)

    checks = envcheck.collect_environment_checks(tmp_path)
    by_name = {check.name: check for check in checks}

    assert by_name["Level Zero loader"].ok is True
    assert by_name["Intel Compute Runtime"].ok is True
    assert by_name["Intel GPU"].ok is True
    assert by_name["whisper-server SYCL"].ok is True
    assert by_name["Modello VAD"].ok is True
    assert by_name["Demucs (opzionale)"].required is False
    assert required_checks_pass_without_oneapi_path(by_name)


def required_checks_pass_without_oneapi_path(by_name: dict[str, envcheck.EnvironmentCheck]) -> bool:
    # /opt/intel/oneapi is intentionally not fabricated in the test runner.
    relevant = [
        check
        for name, check in by_name.items()
        if name != "Intel oneAPI"
    ]
    return envcheck.required_checks_pass(relevant)
