from __future__ import annotations

import threading
import time

import pytest

from core.background_tasks import BackgroundTaskGroup


def test_task_group_tracks_and_reaps_completed_work() -> None:
    release = threading.Event()
    group = BackgroundTaskGroup("Test", join_timeout=1.0)

    group.start("worker", lambda: release.wait(0.5))
    assert group.active_count == 1

    release.set()
    deadline = time.monotonic() + 1.0
    while group.active_count and time.monotonic() < deadline:
        time.sleep(0.01)

    assert group.active_count == 0
    assert group.close() == []


def test_task_group_rejects_new_work_after_close() -> None:
    group = BackgroundTaskGroup("Test", join_timeout=0.01)
    group.close()

    with pytest.raises(RuntimeError, match="task group Test chiuso"):
        group.start("late", lambda: None)


def test_task_group_reports_survivor_after_bounded_close() -> None:
    release = threading.Event()
    group = BackgroundTaskGroup("Test", join_timeout=0.01)
    thread = group.start("slow", release.wait)

    survivors = group.close()

    assert thread.name in survivors
    release.set()
    thread.join(timeout=1.0)
