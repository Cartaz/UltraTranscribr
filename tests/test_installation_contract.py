from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_install_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(ROOT / "install.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_install_script_requires_python_312_or_newer() -> None:
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "python3.11" not in source
    assert "sys.version_info >= (3, 12)" in source
    assert "Python 3.12+ non trovato" in source


def test_install_script_skips_unchanged_expensive_steps() -> None:
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "REQ_MARKER=" in source
    assert "BUILD_MARKER=" in source
    assert "requirements_imports_ok" in source
    assert "whisper_build_is_current" in source
    assert "salto pip install" in source
    assert "salto configurazione e build" in source
    assert "ULTRATRANSCRIBR_FORCE_REBUILD" in source


def test_installer_runs_final_environment_check_without_oneapi_ld_pollution() -> None:
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert '"$VENV/bin/python" -m core.environment_check' in source
    assert "run_environment_check" in source
    assert "env -u LD_LIBRARY_PATH" in source
    assert 'export LD_LIBRARY_PATH="$VENV/lib:${LD_LIBRARY_PATH:-}"' not in source


def test_installer_scopes_oneapi_to_whisper_build_subshell() -> None:
    source = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert "build_whisper_stack() (" in source
    assert 'source "$ONEAPI/setvars.sh"' in source
    assert "build_whisper_stack\n  ensure_default_models" in source
    assert "Inizializzazione Intel oneAPI fallita" in source


def test_installer_reuses_whisper_build_and_builds_only_server_target() -> None:
    source = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert 'if [[ "$FORCE_REBUILD" == "1" ]]; then\n    rm -rf "$WCPP/build"' in source
    assert 'prepare_whisper_source\n  rm -rf "$WCPP/build"' not in source
    assert "-DWHISPER_BUILD_TESTS=OFF" in source
    assert 'cmake --build "$WCPP/build" --target whisper-server' in source


def test_installer_preserves_whisper_shared_library_soname_symlinks() -> None:
    source = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert 'local build_bin="$WCPP/build/bin"' in source
    assert "\\( -type f -o -type l \\)" in source
    assert 'cp -a "$library" "$VENV/lib/"' in source
    assert 'cp -L "$so" "$VENV/lib/"' not in source


def test_installer_verifies_whisper_with_shared_runtime_helper() -> None:
    source = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert "from core.whisper_gpu_detect import verify_sycl_binary" in source
    assert "verify_installed_whisper" in source
    assert "whisper-server SYCL non eseguibile con il runtime oneAPI corrente" in source


def test_installer_uses_the_canonical_default_model() -> None:
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "from config.constants import ProcessDefaults" in source
    assert "manager.get_model_path(ProcessDefaults.MODEL_SIZE)" in source
    assert 'manager.get_model_path("large-v3-turbo")' not in source


def test_xpu_stack_and_demucs_are_mandatory_noninteractive_dependencies() -> None:
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    xpu = (ROOT / "requirements-xpu.txt").read_text(encoding="utf-8")

    assert "ULTRATRANSCRIBR_INSTALL_DEMUCS" not in source
    assert "ask_demucs" not in source
    assert "Installare Demucs" not in source
    assert 'TORCH_VERSION="2.9.1"' in source
    assert 'TORCHAUDIO_VERSION="2.9.1"' in source
    assert 'TORCHCODEC_VERSION="0.9.1"' in source
    assert "download.pytorch.org/whl/xpu" in source
    assert "+xpu" in source
    assert "pyannote.audio==4.0.7" in xpu
    assert "demucs-infer==4.2.2" in xpu


def test_torchcodec_native_import_is_not_required_by_dependency_selfcheck() -> None:
    source = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert "\nimport torchcodec\n" not in source
    assert 'version("torchcodec")' in source
    assert "already-decoded waveforms" in source
    assert "_requirements_imports_probe" in source
    assert "requirements_imports_ok verbose" in source


def test_legacy_sherpa_dependency_is_removed() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "sherpa-onnx" not in requirements


def test_application_log_uses_bounded_rotation() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "RotatingFileHandler" in source
    assert "LOG_MAX_BYTES = 5 * 1024 * 1024" in source
    assert "LOG_BACKUP_COUNT = 4" in source
    assert "maxBytes=LOG_MAX_BYTES" in source
    assert "backupCount=LOG_BACKUP_COUNT" in source
