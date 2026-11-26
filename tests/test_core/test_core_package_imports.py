"""Meeting worker subprocesses import ``core.<module>`` and must stay light."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_importing_a_core_module_does_not_load_the_application() -> None:
    probe = (
        "import sys, core.meeting_engine\n"
        "loaded = [m for m in ('core.app_controller', 'sounddevice', 'PySide6')"
        " if m in sys.modules]\n"
        "print(','.join(loaded))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert result.stdout.strip() == ""
