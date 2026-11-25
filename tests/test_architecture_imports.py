"""Layer boundaries checked on real imports, not on source text.

* ``core`` and ``config`` are UI-free: worker subprocesses and headless tools
  import them without Qt.
* The presentation layer (``ui``) talks to the application only through
  ``core.application_service``; it never reaches the controller or the
  managers it owns.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLICATION_INTERNALS = {
    "core.app_controller",
    "core.meeting_manager",
    "core.file_batch",
    "core.live_sessions",
    "core.dictation_session",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _modules(*packages: str):
    for package in packages:
        yield from sorted((ROOT / package).rglob("*.py"))


def test_core_and_config_never_import_the_ui_or_qt() -> None:
    offenders = {
        str(path.relative_to(ROOT)): sorted(
            name
            for name in _imports(path)
            if name == "ui" or name.startswith(("ui.", "PySide6"))
        )
        for path in _modules("core", "config")
    }
    assert {path: names for path, names in offenders.items() if names} == {}


def test_ui_reaches_the_application_only_through_application_service() -> None:
    offenders = {
        str(path.relative_to(ROOT)): sorted(_imports(path) & APPLICATION_INTERNALS)
        for path in _modules("ui")
    }
    assert {path: names for path, names in offenders.items() if names} == {}


def test_boundary_check_detects_a_forbidden_import(tmp_path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text("from core.app_controller import AppController\nimport PySide6.QtCore\n")
    assert {"core.app_controller", "PySide6.QtCore"} <= _imports(probe)
