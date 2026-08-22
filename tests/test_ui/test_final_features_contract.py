"""UI contracts for the final roadmap features."""
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_final_features_module_is_loaded_after_phase10_hardening() -> None:
    text = (_root() / "ui" / "web" / "settings_cleanup.js").read_text(encoding="utf-8")
    assert 'phase6InjectScript("phase10_hardening.js", "phase10-hardening")' in text
    assert 'phase6InjectScript("final_features.js", "final-features")' in text
    assert text.index("phase10_hardening.js") < text.index("final_features.js")


def test_final_features_expose_session_name_and_backend_controls() -> None:
    text = (_root() / "ui" / "web" / "final_features.js").read_text(encoding="utf-8")
    assert "renameHistorySession" in text
    assert 'name="backend_instances"' in text
    assert 'name="preload_model"' in text


def test_main_window_uses_final_bridge() -> None:
    text = (_root() / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "from ui.final_features_bridge import FinalFeaturesBackendBridge" in text
    assert "Phase10BackendBridge = FinalFeaturesBackendBridge" in text
    assert "self._bridge = Phase10BackendBridge(controller, self)" in text
