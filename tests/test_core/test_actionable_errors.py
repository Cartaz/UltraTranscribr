"""Tests for user-facing error detail propagation."""

from core.exceptions import AppError, SinkNotFoundError


def test_app_error_string_includes_operational_detail() -> None:
    error = AppError("Operazione fallita", detail="Controlla la configurazione e riprova.")
    assert str(error) == "Operazione fallita\nControlla la configurazione e riprova."


def test_sink_error_detail_survives_thread_boundary_stringification() -> None:
    error = SinkNotFoundError(
        "Impossibile trovare automaticamente il sink di Firefox",
        detail="Assicurati che Firefox sia aperto e riproduca audio",
    )
    rendered = str(error)
    assert "sink di Firefox" in rendered
    assert "Firefox sia aperto" in rendered
