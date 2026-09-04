from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_validates_files_before_mutating_queue() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")
    enqueue = source.split("def enqueue(", 1)[1].split("def cancel", 1)[0]

    assert enqueue.index("if not path.is_file()") < enqueue.index("self._jobs.append(")
