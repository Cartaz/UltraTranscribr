from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.file_batch import FileBatchCoordinator


class FakeController:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(language="it", model_size="medium")
        self._handlers = {}
        self._file_thread = None
        self._startup_thread = None
        self.started = []
        self.stopped = 0

    def subscribe(self, event, handler) -> None:
        self._handlers[event] = handler

    def active_live_count(self) -> int:
        return 0

    def is_file_transcribing(self) -> bool:
        return False

    def start_file_transcription(self, path, **kwargs) -> None:
        self.started.append((path, kwargs))

    def stop_file_transcription(self) -> None:
        self.stopped += 1


def test_batch_starts_fifo_and_advances_after_completion(monkeypatch, tmp_path: Path) -> None:
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    controller = FakeController()
    batch = FileBatchCoordinator(controller)
    monkeypatch.setattr(batch, "_maybe_start_next_async", lambda: None)
    monkeypatch.setattr(batch, "_advance_after_worker", lambda: None)

    jobs = batch.enqueue(
        [str(first), str(second)],
        language="it",
        model_size="medium",
    )
    assert [job["status"] for job in jobs] == ["queued", "queued"]

    batch._maybe_start_next()
    assert controller.started[0][0] == str(first)
    assert batch.list_jobs()[0]["status"] == "running"

    batch._on_progress(44)
    assert batch.list_jobs()[0]["progress"] == 44
    batch._on_completed(None)
    assert batch.list_jobs()[0]["status"] == "completed"

    batch._maybe_start_next()
    assert controller.started[1][0] == str(second)
    assert batch.list_jobs()[1]["status"] == "running"
    batch.close()


def test_batch_rejects_missing_file(tmp_path: Path) -> None:
    controller = FakeController()
    batch = FileBatchCoordinator(controller)
    batch._maybe_start_next_async = MagicMock()

    try:
        batch.enqueue(
            [str(tmp_path / "missing.wav")],
            language="it",
            model_size="medium",
        )
    except FileNotFoundError as exc:
        assert "missing.wav" in str(exc)
    else:
        raise AssertionError("missing file must be rejected")
    batch.close()


def test_cancel_marks_active_and_pending_jobs(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    controller = FakeController()
    batch = FileBatchCoordinator(controller)
    monkeypatch.setattr(batch, "_maybe_start_next_async", lambda: None)
    batch.enqueue([str(first), str(second)], language="it", model_size="medium")
    batch._maybe_start_next()

    jobs = batch.cancel(clear_pending=True)

    assert [job["status"] for job in jobs] == ["cancelled", "cancelled"]
    batch.close()


def test_stop_cancels_only_current_job_and_keeps_pending(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    controller = FakeController()
    batch = FileBatchCoordinator(controller)
    monkeypatch.setattr(batch, "_maybe_start_next_async", lambda: None)
    advance = MagicMock()
    monkeypatch.setattr(batch, "_advance_after_worker", advance)
    batch.enqueue([str(first), str(second)], language="it", model_size="medium")
    batch._maybe_start_next()

    batch._on_status("stopped")

    assert [job["status"] for job in batch.list_jobs()] == ["cancelled", "queued"]
    advance.assert_called_once_with()
    batch.close()


def test_pending_batch_advances_after_external_file_completion(tmp_path: Path, monkeypatch) -> None:
    queued = tmp_path / "queued.wav"
    queued.write_bytes(b"q")
    controller = FakeController()
    batch = FileBatchCoordinator(controller)
    monkeypatch.setattr(batch, "_maybe_start_next_async", lambda: None)
    advance = MagicMock()
    monkeypatch.setattr(batch, "_advance_after_worker", advance)
    batch.enqueue([str(queued)], language="it", model_size="medium")

    # No active batch id: this terminal event belongs to a File/recovery job
    # that was already running when the batch was enqueued.
    batch._on_completed(None)

    assert batch.list_jobs()[0]["status"] == "queued"
    advance.assert_called_once_with()
    batch.close()


def test_clear_finished_preserves_pending_jobs(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    controller = FakeController()
    batch = FileBatchCoordinator(controller)
    monkeypatch.setattr(batch, "_maybe_start_next_async", lambda: None)
    monkeypatch.setattr(batch, "_advance_after_worker", lambda: None)
    batch.enqueue([str(first), str(second)], language="it", model_size="medium")
    batch._maybe_start_next()
    batch._on_completed(None)

    jobs = batch.clear_finished()

    assert len(jobs) == 1
    assert jobs[0]["path"] == str(second)
    assert jobs[0]["status"] == "queued"
    batch.close()
