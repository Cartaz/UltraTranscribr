from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from core.meeting_batch import MeetingBatchCoordinator


class _FakeMeetingManager:
    def __init__(self) -> None:
        self.busy = False
        self.starts: list[tuple[str, str | None, int]] = []
        self.cancel_calls = 0
        self._counter = 0
        self.handlers: dict[str, list[Callable[[Any], None]]] = {}

    def is_busy(self) -> bool:
        return self.busy

    def start_file(
        self,
        file_path: Path | str,
        *,
        language: str | None = None,
        num_speakers: int = 0,
    ) -> dict[str, Any]:
        self._counter += 1
        self.busy = True
        self.starts.append((str(file_path), language, num_speakers))
        return {
            "id": f"meeting-{self._counter}",
            "status": "preparing_file",
            "progress": 0,
            "diarization_progress": 0,
        }

    def cancel(self) -> None:
        self.cancel_calls += 1

    def subscribe(self, event: str, handler: Callable[[Any], None]) -> None:
        self.handlers.setdefault(event, []).append(handler)

    def unsubscribe(self, event: str, handler: Callable[[Any], None]) -> None:
        values = self.handlers.get(event, [])
        if handler in values:
            values.remove(handler)

    def emit(self, event: str, payload: Any) -> None:
        for handler in list(self.handlers.get(event, [])):
            handler(payload)


@pytest.fixture
def harness():
    manager = _FakeMeetingManager()
    emitted: list[tuple[str, Any]] = []
    queue = MeetingBatchCoordinator(
        manager,
        subscribe=manager.subscribe,
        unsubscribe=manager.unsubscribe,
        event_sink=lambda event, payload: emitted.append((event, payload)),
    )
    # Unit tests drive scheduling deterministically; BackgroundTaskGroup behavior is
    # already covered separately and production still uses its asynchronous path.
    queue._maybe_start_next_async = queue._maybe_start_next  # type: ignore[method-assign]
    try:
        yield manager, queue, emitted
    finally:
        queue.close()


def _entry(path: Path, language: str = "it", speakers: int = 0) -> dict[str, Any]:
    return {
        "path": str(path),
        "language": language,
        "num_speakers": speakers,
    }


def _finish(manager: _FakeMeetingManager, session_id: str, status: str, error: str = "") -> None:
    manager.emit(
        "meeting_updated",
        {
            "id": session_id,
            "status": status,
            "progress": 100 if status == "completed" else 43,
            "diarization_progress": 100 if status == "completed" else 17,
            "error": error,
        },
    )
    manager.busy = False
    manager.emit("history_changed", session_id)


def test_batch_runs_fifo_with_independent_per_file_settings(harness, tmp_path: Path) -> None:
    manager, queue, _ = harness
    first = tmp_path / "one.wav"
    second = tmp_path / "two.wav"
    third = tmp_path / "three.wav"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    third.write_bytes(b"three")

    queue.enqueue(
        [
            _entry(first, "it", 5),
            _entry(second, "it", 4),
            _entry(third, "en", 9),
        ]
    )

    assert manager.starts == [(str(first), "it", 5)]
    jobs = queue.list_jobs()
    assert [job["status"] for job in jobs] == ["running", "queued", "queued"]
    assert [(job["language"], job["num_speakers"]) for job in jobs] == [
        ("it", 5),
        ("it", 4),
        ("en", 9),
    ]

    _finish(manager, "meeting-1", "completed")
    assert manager.starts[-1] == (str(second), "it", 4)

    _finish(manager, "meeting-2", "completed")
    assert manager.starts[-1] == (str(third), "en", 9)

    _finish(manager, "meeting-3", "completed")
    assert [job["status"] for job in queue.list_jobs()] == [
        "completed",
        "completed",
        "completed",
    ]
    assert queue.is_busy() is False


def test_batch_tracks_both_pipeline_progresses(harness, tmp_path: Path) -> None:
    manager, queue, emitted = harness
    source = tmp_path / "meeting.flac"
    source.write_bytes(b"audio")
    queue.enqueue([_entry(source, "auto", 0)])

    manager.emit(
        "meeting_updated",
        {
            "id": "meeting-1",
            "status": "diarizing",
            "progress": 100,
            "diarization_progress": 37,
            "error": "",
        },
    )

    job = queue.list_jobs()[0]
    assert job["phase"] == "diarizing"
    assert job["transcription_progress"] == 100
    assert job["diarization_progress"] == 37
    assert any(event == "meeting_queue_job_updated" for event, _ in emitted)


def test_failed_job_does_not_stop_following_meetings(harness, tmp_path: Path) -> None:
    manager, queue, _ = harness
    first = tmp_path / "bad.wav"
    second = tmp_path / "good.wav"
    first.write_bytes(b"bad")
    second.write_bytes(b"good")
    queue.enqueue([_entry(first), _entry(second, speakers=4)])

    _finish(manager, "meeting-1", "error", "forced failure")

    jobs = queue.list_jobs()
    assert jobs[0]["status"] == "error"
    assert jobs[0]["error"] == "forced failure"
    assert jobs[1]["status"] == "running"
    assert manager.starts[-1] == (str(second), "it", 4)


def test_cancel_stops_active_and_marks_pending_jobs_cancelled(harness, tmp_path: Path) -> None:
    manager, queue, _ = harness
    entries = []
    for index in range(3):
        path = tmp_path / f"{index}.wav"
        path.write_bytes(b"audio")
        entries.append(_entry(path, speakers=index + 2))
    queue.enqueue(entries)

    queue.cancel(clear_pending=True)

    jobs = queue.list_jobs()
    assert manager.cancel_calls == 1
    assert jobs[0]["status"] == "cancelling"
    assert [job["status"] for job in jobs[1:]] == ["cancelled", "cancelled"]

    _finish(manager, "meeting-1", "cancelled")
    assert len(manager.starts) == 1
    assert queue.is_busy() is False


def test_enqueue_deduplicates_one_request_and_keeps_first_configuration(harness, tmp_path: Path) -> None:
    _, queue, _ = harness
    source = tmp_path / "same.wav"
    source.write_bytes(b"audio")

    jobs = queue.enqueue(
        [
            _entry(source, "it", 5),
            _entry(source, "en", 9),
        ]
    )

    assert len(jobs) == 1
    assert jobs[0]["language"] == "it"
    assert jobs[0]["num_speakers"] == 5


def test_enqueue_validates_whole_request_before_mutating_queue(harness, tmp_path: Path) -> None:
    _, queue, _ = harness
    valid = tmp_path / "valid.wav"
    valid.write_bytes(b"audio")

    with pytest.raises(FileNotFoundError):
        queue.enqueue(
            [
                _entry(valid, "it", 4),
                _entry(tmp_path / "missing.wav", "it", 5),
            ]
        )
    assert queue.list_jobs() == []

    with pytest.raises(ValueError, match="tra 0 e 20"):
        queue.enqueue([_entry(valid, "it", 21)])
    assert queue.list_jobs() == []

    with pytest.raises(ValueError, match="lingua"):
        queue.enqueue([_entry(valid, "", 4)])
    assert queue.list_jobs() == []


def test_clear_finished_keeps_only_actionable_jobs(harness, tmp_path: Path) -> None:
    manager, queue, _ = harness
    first = tmp_path / "one.wav"
    second = tmp_path / "two.wav"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    queue.enqueue([_entry(first), _entry(second)])
    _finish(manager, "meeting-1", "completed")

    jobs = queue.clear_finished()
    assert len(jobs) == 1
    assert jobs[0]["path"] == str(second)
    assert jobs[0]["status"] == "running"


def test_close_unsubscribes_from_meeting_lifecycle(harness) -> None:
    manager, queue, _ = harness
    queue.close()

    assert manager.handlers["meeting_updated"] == []
    assert manager.handlers["history_changed"] == []
