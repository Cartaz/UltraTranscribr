# tests/test_config/test_settings.py
"""Test per le impostazioni dell'applicazione unificata."""

import pytest

from config.settings import AudioSource, ComputeDevice, ModelSize, Settings


class TestModelSize:
    """Test per l'enum ModelSize."""

    def test_default_is_turbo(self) -> None:
        """Il modello predefinito deve essere TURBO (large-v3-turbo)."""
        assert ModelSize.default() == ModelSize.TURBO

    def test_choices_contains_all(self) -> None:
        """La lista choices deve contenere tutti i valori."""
        choices = ModelSize.choices()
        assert len(choices) == len(list(ModelSize))
        assert "small" in choices
        assert "tiny.en" in choices


class TestAudioSource:
    """Test per l'enum AudioSource."""

    def test_has_firefox(self) -> None:
        """Deve contenere FIREFOX."""
        assert AudioSource.FIREFOX.value == "firefox"

    def test_has_microphone(self) -> None:
        """Deve contenere MICROPHONE."""
        assert AudioSource.MICROPHONE.value == "microphone"

    def test_choices(self) -> None:
        """La lista choices deve contenere entrambe le fonti."""
        choices = AudioSource.choices()
        assert "firefox" in choices
        assert "microphone" in choices


class TestSettings:
    """Test per la dataclass Settings."""

    def test_default_values(self) -> None:
        """Verifica i valori predefiniti delle impostazioni."""
        s = Settings()
        assert s.sample_rate == 16000
        assert s.channels == 1
        assert s.chunk_ms == 3000
        assert s.model_size == ModelSize.TURBO.value
        # Backend fisso a SYCL (nessun fallback CPU nella versione attuale)
        assert s.device == ComputeDevice.SYCL.value
        assert s.compute_type == "f16"
        assert s.language == "en"
        assert s.audio_source == AudioSource.FIREFOX.value
        assert s.sink_name is None

    def test_with_override(self) -> None:
        """with_ deve restituire una nuova Settings con il campo sostituito."""
        s = Settings()
        s2 = s.with_(model_size="medium", language="it")
        assert s2.model_size == "medium"
        assert s2.language == "it"
        # L'originale non deve cambiare (immutabilita)
        assert s.model_size == ModelSize.TURBO.value
        assert s.language == "en"

    def test_with_invalid_key_raises(self) -> None:
        """with_ deve sollevare AttributeError per chiavi non esistenti."""
        s = Settings()
        with pytest.raises(AttributeError, match="non ha il campo"):
            s.with_(nonexistent_key=42)

    def test_chunk_samples_property(self) -> None:
        """chunk_samples deve essere calcolato correttamente."""
        s = Settings()
        assert s.chunk_samples == 16000 * 3000 // 1000

    def test_frozen_immutability(self) -> None:
        """Settings deve essere immutabile (frozen dataclass)."""
        s = Settings()
        with pytest.raises(AttributeError):
            s.model_size = "large"  # type: ignore[misc]

    def test_audio_source_override(self) -> None:
        """Deve poter cambiare la fonte audio con with_."""
        s = Settings()
        s_mic = s.with_(audio_source=AudioSource.MICROPHONE.value)
        assert s_mic.audio_source == "microphone"
        assert s.audio_source == "firefox"
