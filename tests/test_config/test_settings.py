# tests/test_config/test_settings.py
"""Test per le impostazioni dell'applicazione unificata."""

import json

import pytest

from config.constants import AppMeta, ProcessDefaults
from config.settings import AudioSource, ComputeDevice, ModelSize, Settings


class TestModelSize:
    """Test per l'enum ModelSize."""

    def test_default_is_large_v3(self) -> None:
        assert ModelSize.default() == ModelSize.LARGE_V3

    def test_choices_exposes_only_managed_models(self) -> None:
        assert ModelSize.choices() == ["large-v3", "large-v3-turbo", "medium"]
        assert "small" not in ModelSize.choices()
        assert "tiny.en" not in ModelSize.choices()


class TestAudioSource:
    """Test per l'enum AudioSource."""

    def test_has_system_audio(self) -> None:
        assert AudioSource.SYSTEM.value == "system"

    def test_has_application_stream(self) -> None:
        assert AudioSource.APPLICATION.value == "application"

    def test_legacy_firefox_symbol_is_system_alias(self) -> None:
        assert AudioSource.FIREFOX is AudioSource.SYSTEM

    def test_has_microphone(self) -> None:
        assert AudioSource.MICROPHONE.value == "microphone"

    def test_choices_exposes_only_current_sources(self) -> None:
        assert AudioSource.choices() == ["system", "application", "microphone"]
        assert "firefox" not in AudioSource.choices()


class TestSettings:
    """Test per la dataclass Settings."""

    def test_default_values(self) -> None:
        s = Settings()
        assert s.sample_rate == 16000
        assert s.channels == 1
        assert s.chunk_ms == 3000
        assert s.model_size == ModelSize.LARGE_V3.value
        assert s.device == ComputeDevice.SYCL.value
        assert s.compute_type == "f16"
        assert s.language == "en"
        assert s.audio_source == AudioSource.SYSTEM.value
        assert s.sink_name is None
        assert s.sink_search_keyword == ""

    def test_with_override(self) -> None:
        s = Settings()
        s2 = s.with_(model_size="medium", language="it")
        assert s2.model_size == "medium"
        assert s2.language == "it"
        assert s.model_size == ModelSize.LARGE_V3.value
        assert s.language == "en"

    def test_hidden_model_is_not_a_valid_user_setting(self) -> None:
        with pytest.raises(ValueError, match="model_size non valido"):
            Settings(model_size="tiny")

    def test_load_migrates_old_hidden_model_without_losing_other_settings(
        self, tmp_path, monkeypatch
    ) -> None:
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(
            json.dumps({"model_size": "tiny", "language": "it", "beam_size": 7}),
            encoding="utf-8",
        )
        monkeypatch.setattr(AppMeta, "SETTINGS_PATH", settings_path)

        loaded = Settings.load()

        assert loaded.model_size == ProcessDefaults.MODEL_SIZE
        assert loaded.language == "it"
        assert loaded.beam_size == 7

    def test_with_invalid_key_raises(self) -> None:
        s = Settings()
        with pytest.raises(AttributeError, match="non ha il campo"):
            s.with_(nonexistent_key=42)

    def test_chunk_samples_property(self) -> None:
        s = Settings()
        assert s.chunk_samples == 16000 * 3000 // 1000

    def test_frozen_immutability(self) -> None:
        s = Settings()
        with pytest.raises(AttributeError):
            s.model_size = "large"  # type: ignore[misc]

    def test_audio_source_override(self) -> None:
        s = Settings()
        s_app = s.with_(audio_source=AudioSource.APPLICATION.value)
        s_mic = s.with_(audio_source=AudioSource.MICROPHONE.value)
        assert s_app.audio_source == "application"
        assert s_mic.audio_source == "microphone"
        assert s.audio_source == "system"
