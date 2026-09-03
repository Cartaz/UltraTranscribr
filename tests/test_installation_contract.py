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


def test_installer_runs_final_environment_check() -> None:
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert '"$VENV/bin/python" -m core.environment_check' in source
    assert "run_environment_check" in source


def test_installer_uses_the_canonical_default_model() -> None:
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "from config.constants import ProcessDefaults" in source
    assert "manager.get_model_path(ProcessDefaults.MODEL_SIZE)" in source
    assert 'manager.get_model_path("large-v3-turbo")' not in source


def test_demucs_remains_optional_and_noninteractive_safe() -> None:
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "ULTRATRANSCRIBR_INSTALL_DEMUCS" in source
    assert "[[ -t 0 ]]" in source
    assert "ask_demucs || return 0" in source


def test_application_log_uses_bounded_rotation() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "RotatingFileHandler" in source
    assert "LOG_MAX_BYTES = 5 * 1024 * 1024" in source
    assert "LOG_BACKUP_COUNT = 4" in source
    assert "maxBytes=LOG_MAX_BYTES" in source
    assert "backupCount=LOG_BACKUP_COUNT" in source
