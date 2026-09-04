from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_marks_job_starting_before_invoking_meeting_manager() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")
    method = source.split("def _maybe_start_next", 1)[1].split("def _on_meeting_updated", 1)[0]

    assert method.index('job.status = "starting"') < method.index("self._manager.start_file(")
