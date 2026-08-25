"""History post-processing orchestration outside the presentation layer."""
from __future__ import annotations

from typing import Any, Optional, Protocol

from core.transcript_postprocess import process_text


class _DerivedOutputStore(Protocol):
    def save_derived_output(self, session_id: str, profile: str, text: str) -> None: ...


class HistoryPostprocessSource(Protocol):
    """Narrow application surface required for derived transcript generation."""

    @property
    def history(self) -> _DerivedOutputStore: ...

    def get_history_session(self, session_id: str) -> Optional[dict[str, Any]]: ...

    def notify_history_changed(self, session_id: str) -> None: ...


def generate_history_postprocess(
    source: HistoryPostprocessSource,
    session_id: str,
    profile: str,
) -> dict[str, str]:
    """Generate, persist and publish one derived transcript output."""
    session = source.get_history_session(session_id)
    if not session:
        raise KeyError("sessione non trovata")

    derived = process_text(str(session.get("text") or ""), profile)
    source.history.save_derived_output(session_id, profile, derived)
    source.notify_history_changed(session_id)
    return {"profile": profile, "text": derived}
