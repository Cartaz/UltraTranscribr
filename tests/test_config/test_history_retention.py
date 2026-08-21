"""Validation tests for transcript history retention settings."""
import pytest

from config.settings import Settings


def test_history_retention_accepts_zero_and_reasonable_values() -> None:
    assert Settings(history_retention_days=0).history_retention_days == 0
    assert Settings(history_retention_days=90).history_retention_days == 90
    assert Settings(history_retention_days=3650).history_retention_days == 3650


def test_history_retention_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError):
        Settings(history_retention_days=-1)
    with pytest.raises(ValueError):
        Settings(history_retention_days=3651)
