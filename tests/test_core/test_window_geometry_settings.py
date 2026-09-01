import json

import pytest

from config.constants import AppMeta
from config.settings import Settings


def test_window_coordinates_accept_negative_multi_monitor_positions() -> None:
    settings = Settings(window_x=-1536, window_y=120, window_width=1400, window_height=900)

    assert settings.window_x == -1536
    assert settings.window_y == 120


@pytest.mark.parametrize("field", ["window_x", "window_y"])
def test_window_coordinates_reject_non_integer_values(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        Settings(**{field: True})


def test_window_geometry_round_trips_through_settings_file(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(AppMeta, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(AppMeta, "SETTINGS_PATH", settings_path)

    Settings(
        language="en",
        window_x=-120,
        window_y=75,
        window_width=1500,
        window_height=920,
    ).save()
    loaded = Settings.load()

    assert loaded.language == "en"
    assert (loaded.window_x, loaded.window_y) == (-120, 75)
    assert (loaded.window_width, loaded.window_height) == (1500, 920)


def test_malformed_coordinate_is_recovered_without_discarding_other_settings(
    tmp_path, monkeypatch
) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(AppMeta, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(AppMeta, "SETTINGS_PATH", settings_path)
    settings_path.write_text(
        json.dumps(
            {
                "language": "en",
                "window_x": "not-a-coordinate",
                "window_y": 55,
                "window_width": 1400,
                "window_height": 850,
            }
        ),
        encoding="utf-8",
    )

    loaded = Settings.load()

    assert loaded.language == "en"
    assert loaded.window_x is None
    assert loaded.window_y == 55
    assert (loaded.window_width, loaded.window_height) == (1400, 850)
