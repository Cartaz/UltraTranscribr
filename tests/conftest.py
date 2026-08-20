# tests/conftest.py
"""Fixture condivise per i test dell'applicazione unificata."""

import pytest

from core.event_bus import EventBus


@pytest.fixture(autouse=True)
def _reset_event_bus():
    """Resetta il singleton EventBus prima e dopo ogni test."""
    EventBus.reset()
    yield
    EventBus.reset()
