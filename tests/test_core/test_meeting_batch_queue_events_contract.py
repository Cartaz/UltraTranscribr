from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_emits_only_queue_presentation_events() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")

    assert 'self._event_sink("meeting_queue_job_updated", payload)' in source
    assert 'self._event_sink("meeting_queue_changed", self.list_jobs())' in source
