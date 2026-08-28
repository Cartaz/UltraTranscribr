import threading
import time

from core.inference_scheduler import InferencePriority, InferenceScheduler


def test_interactive_beats_batch_when_capacity_returns():
    scheduler = InferenceScheduler(["gpu"], aging_seconds=60)
    resource, _ = scheduler.acquire(InferencePriority.LIVE)
    order = []

    def worker(name, priority):
        item, _ = scheduler.acquire(priority)
        order.append(name)
        time.sleep(0.01)
        scheduler.release(item)

    batch = threading.Thread(target=worker, args=("batch", InferencePriority.BATCH))
    interactive = threading.Thread(target=worker, args=("interactive", InferencePriority.INTERACTIVE))
    batch.start()
    time.sleep(0.02)
    interactive.start()
    time.sleep(0.02)
    scheduler.release(resource)
    batch.join(1)
    interactive.join(1)
    assert order == ["interactive", "batch"]


def test_fifo_within_same_priority():
    scheduler = InferenceScheduler([1], aging_seconds=60)
    resource, _ = scheduler.acquire("live")
    order = []

    def worker(name):
        item, _ = scheduler.acquire("live")
        order.append(name)
        scheduler.release(item)

    first = threading.Thread(target=worker, args=("first",))
    second = threading.Thread(target=worker, args=("second",))
    first.start(); time.sleep(0.01); second.start(); time.sleep(0.01)
    scheduler.release(resource)
    first.join(1); second.join(1)
    assert order == ["first", "second"]


def test_aging_prevents_batch_starvation():
    now = [0.0]
    scheduler = InferenceScheduler([1], aging_seconds=10.0, clock=lambda: now[0])
    resource, _ = scheduler.acquire("live")
    order = []

    def worker(name, priority):
        item, _ = scheduler.acquire(priority)
        order.append(name)
        scheduler.release(item)

    batch = threading.Thread(target=worker, args=("batch", "batch"))
    batch.start(); time.sleep(0.02)
    now[0] = 25.0
    interactive = threading.Thread(target=worker, args=("interactive", "interactive"))
    interactive.start(); time.sleep(0.02)
    scheduler.release(resource)
    batch.join(1); interactive.join(1)
    assert order[0] == "batch"


def test_close_wakes_waiter():
    scheduler = InferenceScheduler([1])
    resource, _ = scheduler.acquire("live")
    errors = []

    def waiter():
        try:
            scheduler.acquire("interactive")
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=waiter)
    thread.start(); time.sleep(0.02)
    scheduler.close(); thread.join(1)
    assert errors == ["scheduler inferenza chiuso"]
    scheduler.release(resource)
