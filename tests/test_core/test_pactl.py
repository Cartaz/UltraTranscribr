"""Deterministic lifecycle tests for managed pactl subprocesses."""
from __future__ import annotations

import subprocess
import threading

import core.pactl as pactl_module
from core.pactl import PactlRunner


class FakeProcess:
    def __init__(self, *, stubborn: bool = False, block: bool = False) -> None:
        self.pid = 4242
        self.returncode = None
        self.stderr = ""
        self.stdout = ""
        self.terminated = False
        self.killed = False
        self.stubborn = stubborn
        self.block = block
        self.released = threading.Event()

    def communicate(self, timeout=None):
        if self.block and self.returncode is None:
            if not self.released.wait(timeout=timeout):
                raise subprocess.TimeoutExpired("pactl", timeout)
        if self.returncode is None:
            self.returncode = 0
        return self.stdout, self.stderr

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self.stubborn:
            self.returncode = -15
            self.released.set()

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.released.set()


def test_timeout_terminates_and_reaps_child(monkeypatch) -> None:
    process = FakeProcess(block=True)
    monkeypatch.setattr(pactl_module.subprocess, "Popen", lambda *a, **k: process)

    runner = PactlRunner()
    assert runner.run(["info"], timeout=0.01) is None
    assert process.terminated is True
    assert process.poll() is not None


def test_stubborn_child_escalates_from_terminate_to_kill(monkeypatch) -> None:
    process = FakeProcess(stubborn=True, block=True)
    monkeypatch.setattr(pactl_module.subprocess, "Popen", lambda *a, **k: process)

    runner = PactlRunner()
    assert runner.run(["info"], timeout=0.01) is None
    assert process.terminated is True
    assert process.killed is True
    assert process.poll() is not None


def test_close_interrupts_inflight_command_and_rejects_new_work(monkeypatch) -> None:
    process = FakeProcess(block=True)
    monkeypatch.setattr(pactl_module.subprocess, "Popen", lambda *a, **k: process)
    runner = PactlRunner()
    result = []

    thread = threading.Thread(
        target=lambda: result.append(runner.run(["list", "sink-inputs"], timeout=30.0))
    )
    thread.start()
    while not runner._processes:
        pass

    runner.close()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert process.terminated is True
    assert result == [None]
    assert runner.run(["info"]) is None
