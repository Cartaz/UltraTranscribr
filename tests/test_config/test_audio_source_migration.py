"""Regression tests for Firefox -> system audio settings migration."""
from __future__ import annotations

import json

from config.constants import AppMeta
from config.settings import Settings


def test_legacy_firefox_source_migrates_without_losing_other_settings(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({
            "audio_source": "firefox",
            "sink_search_keyword": "Firefox",
            "language": "it",
            "model_size": "medium",
            "beam_size": 7,
            "window_width": 1300,
            "window_height": 850,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(AppMeta, "SETTINGS_PATH", settings_path)

    settings = Settings.load()

    assert settings.audio_source == "system"
    assert settings.sink_search_keyword == ""
    assert settings.language == "it"
    assert settings.model_size == "medium"
    assert settings.beam_size == 7
    assert settings.window_width == 1300
    assert settings.window_height == 850
