"""Regression guard for WebChannel subscription lifecycle ownership."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_bridge_does_not_duplicate_application_subscription_registry() -> None:
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")

    assert "self._subscriptions" not in bridge
    assert "self._application.subscribe(event, handler)" in bridge
    assert "self._subscriptions" in application
    assert "self.controller.unsubscribe(event, handler)" in application
