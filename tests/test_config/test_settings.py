# tests/test_config/test_settings.py
"""Test per le impostazioni dell'applicazione unificata."""

import pytest

from config.settings import AudioSource, ComputeDevice, ModelSize, Settings


class TestModelSize:
    """Test per l'enum ModelSize."""

    def test_default_is_turbo(self) -> None:
        assert ModelSize.default() == ModelSize.TURBO

    def test_choices_contains_all(self) -> None:
        choices = ModelSize.choices()
        assert len(choices) == len(list(ModelSize))
        assert "small" in choices
        assert "tiny.en" in choices


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
        assert s.model_size == ModelSize.TURBO.value
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
        assert s.model_size == ModelSize.TURBO.value
        assert s.language == "en"

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
