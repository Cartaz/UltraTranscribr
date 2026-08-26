"""Tests for core-owned derived transcript generation."""
from __future__ import annotations

from core.event_bus import EventBus
from core.history_postprocess import generate_history_postprocess


class FakeHistory:
    def __init__(self) -> None:
        self.saved = None

    def save_derived_output(self, session_id: str, profile: str, text: str) -> None:
        self.saved = (session_id, profile, text)


class FakeSource:
    def __init__(self, session=None) -> None:
        self.history = FakeHistory()
        self.session = session

    def get_history_session(self, session_id: str):
        del session_id
        return self.session


def test_generate_history_postprocess_transforms_persists_and_publishes() -> None:
    source = FakeSource({"text": "Uno.   Due. Tre.    Quattro."})
    changed = []
    handler = changed.append
    EventBus().subscribe("history_changed", handler)
    try:
        result = generate_history_postprocess(source, "session-a", "clean")
    finally:
        EventBus().unsubscribe("history_changed", handler)

    assert result == {"profile": "clean", "text": "Uno. Due. Tre. Quattro."}
    assert source.history.saved == (
        "session-a",
        "clean",
        "Uno. Due. Tre. Quattro.",
    )
    assert changed == ["session-a"]


def test_generate_history_postprocess_rejects_missing_session() -> None:
    source = FakeSource(None)

    try:
        generate_history_postprocess(source, "missing", "clean")
    except KeyError as exc:
        assert "sessione non trovata" in str(exc)
    else:
        raise AssertionError("missing session must fail")

    assert source.history.saved is None
