import json

import pytest

from config.constants import AppMeta, UIConstraints
from config.settings import Settings


def test_default_and_minimum_window_size_are_1200x800() -> None:
    assert UIConstraints.MIN_WINDOW_WIDTH == 1200
    assert UIConstraints.MIN_WINDOW_HEIGHT == 800
    assert UIConstraints.WINDOW_WIDTH == 1200
    assert UIConstraints.WINDOW_HEIGHT == 800

    settings = Settings()
    assert settings.window_width == 1200
    assert settings.window_height == 800


def test_settings_reject_window_sizes_below_minimum() -> None:
    with pytest.raises(ValueError, match="window_width"):
        Settings(window_width=1199)

    with pytest.raises(ValueError, match="window_height"):
        Settings(window_height=799)


def test_loading_legacy_window_size_clamps_without_resetting_other_settings(
    tmp_path, monkeypatch
) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "window_width": 484,
                "window_height": 540,
                "language": "it",
                "model_size": "large-v3",
                "beam_size": 7,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(AppMeta, "SETTINGS_PATH", settings_path)

    settings = Settings.load()

    assert settings.window_width == 1200
    assert settings.window_height == 800
    assert settings.language == "it"
    assert settings.model_size == "large-v3"
    assert settings.beam_size == 7
