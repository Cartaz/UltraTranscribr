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


def test_failed_thread_start_does_not_leave_owned_task(monkeypatch):
    group=BackgroundTaskGroup('Failure')
    def fail(thread):
        raise RuntimeError('cannot start thread')
    monkeypatch.setattr(threading.Thread,'start',fail)
    with pytest.raises(RuntimeError,match='cannot start'):
        group.start('worker',lambda:None)
    assert not group._threads
    assert group.close() == []


def test_start_is_atomic_with_shutdown(monkeypatch):
    group=BackgroundTaskGroup('Race',join_timeout=1)
    entered=threading.Event(); release=threading.Event(); closing=threading.Event(); closed=threading.Event(); ran=threading.Event()
    original=threading.Thread.start
    def start(thread):
        if thread.name=='Race-worker':
            entered.set()
            assert release.wait(2)
        original(thread)
    monkeypatch.setattr(threading.Thread,'start',start)
    starter=threading.Thread(target=lambda:group.start('worker',ran.set)); starter.start()
    assert entered.wait(1)
    def close():
        closing.set(); group.close(); closed.set()
    closer=threading.Thread(target=close); closer.start()
    assert closing.wait(1)
    assert not closed.wait(.05)
    release.set(); starter.join(2); closer.join(2)
    assert ran.is_set() and closed.is_set() and group.active_count==0
