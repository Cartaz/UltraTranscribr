from __future__ import annotations

from pathlib import Path

import pytest

from config.settings import Settings
from core.application_service import ApplicationService


class _Queue:
    def __init__(self, busy: bool = False) -> None:
        self.busy = busy

    def is_busy(self) -> bool:
        return self.busy

    def list_jobs(self):
        return [{"status": "running"}] if self.busy else []


class _Meeting:
    def __init__(self, busy: bool = False) -> None:
        self.busy = busy

    def is_busy(self) -> bool:
        return self.busy


class _Controller:
    def __init__(self) -> None:
        self.settings = Settings(language="it", model_size="large-v3")
        self.file_batch = _Queue(False)
        self.meeting = _Meeting(False)
        self.history = type("History", (), {"migrate_legacy_session_names": lambda self: None})()
        self._subscriptions = []
        self.live_count = 0
        self.file_busy = False
        self.dictation = False

    def subscribe(self, event, handler) -> None:
        self._subscriptions.append((event, handler))

    def unsubscribe(self, event, handler) -> None:
        item = (event, handler)
        if item in self._subscriptions:
            self._subscriptions.remove(item)

    def active_live_count(self) -> int:
        return self.live_count

    def is_file_busy(self) -> bool:
        return self.file_busy

    def dictation_busy(self) -> bool:
        return self.dictation


@pytest.fixture
def service():
    controller = _Controller()
    application = ApplicationService(controller)  # type: ignore[arg-type]
    try:
        yield controller, application
    finally:
        application.close()


def _job(path: Path, *, language: str = "it", speakers: int = 0) -> dict[str, object]:
    return {
        "path": str(path),
        "language": language,
        "num_speakers": speakers,
    }


def test_meeting_batch_enqueue_rejects_competing_workflows(service, tmp_path: Path) -> None:
    controller, application = service
    source = tmp_path / "meeting.wav"
    source.write_bytes(b"audio")
    entries = [_job(source)]

    controller.file_batch.busy = True
    with pytest.raises(RuntimeError, match="coda File"):
        application.enqueue_meeting_files(entries)
    controller.file_batch.busy = False

    controller.live_count = 1
    with pytest.raises(RuntimeError, match="Live, File o Dettatura"):
        application.enqueue_meeting_files(entries)
    controller.live_count = 0

    controller.file_busy = True
    with pytest.raises(RuntimeError, match="Live, File o Dettatura"):
        application.enqueue_meeting_files(entries)
    controller.file_busy = False

    controller.dictation = True
    with pytest.raises(RuntimeError, match="Live, File o Dettatura"):
        application.enqueue_meeting_files(entries)


def test_application_defaults_blank_per_file_language_in_python(service, tmp_path: Path) -> None:
    _, application = service
    source = tmp_path / "meeting.wav"
    source.write_bytes(b"audio")
    captured = []
    application.meeting_batch.enqueue = lambda entries: captured.extend(entries) or entries  # type: ignore[method-assign]

    application.enqueue_meeting_files([_job(source, language="", speakers=9)])

    assert captured == [
        {
            "path": str(source),
            "language": "it",
            "num_speakers": 9,
        }
    ]


def test_active_meeting_batch_blocks_manual_meeting_and_file_workflows(service) -> None:
    _, application = service
    application.meeting_batch.is_busy = lambda: True  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="coda Riunioni"):
        application._require_meeting_start_available()

    with pytest.raises(RuntimeError, match="coda Riunioni"):
        application.enqueue_files(
            [],
            language="it",
            model_size="large-v3",
            song_mode=False,
            isolate_vocals=False,
        )
