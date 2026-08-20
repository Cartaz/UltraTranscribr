# tests/test_core/test_models.py
"""Test per i modelli dati dell'applicazione."""

import pytest

from core.models import ProcessState, StatusEnum


class TestStatusEnum:
    """Test per l'enum StatusEnum."""

    def test_all_values_exist(self) -> None:
        """Deve contenere tutti gli stati previsti."""
        expected = {"idle", "running", "buffering", "error",
                    "loading_model", "isolating_vocals",
                    "stopped", "completed"}
        actual = {s.value for s in StatusEnum}
        assert actual == expected

    def test_string_type(self) -> None:
        """I valori devono essere stringhe."""
        for status in StatusEnum:
            assert isinstance(status.value, str)


class TestProcessState:
    """Test per la dataclass ProcessState."""

    def test_defaults(self) -> None:
        """I valori predefiniti devono essere corretti."""
        ps = ProcessState(process_id="test")
        assert ps.process_id == "test"
        assert ps.status == StatusEnum.IDLE
        assert ps.sink_name is None
        assert ps.model_size is None
        assert ps.error_message is None

    def test_frozen(self) -> None:
        """ProcessState deve essere immutabile."""
        ps = ProcessState(process_id="test")
        with pytest.raises(AttributeError):
            ps.status = "running"  # type: ignore[misc]

    def test_custom_values(self) -> None:
        """Deve accettare valori personalizzati."""
        ps = ProcessState(
            process_id="custom",
            status=StatusEnum.RUNNING,
            sink_name="alsa_output.monitor",
            model_size="large-v3",
            error_message="test error",
        )
        assert ps.status == StatusEnum.RUNNING
        assert ps.sink_name == "alsa_output.monitor"
        assert ps.model_size == "large-v3"
        assert ps.error_message == "test error"
