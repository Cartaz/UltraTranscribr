"""Shutdown must not leave portal tasks with unretrieved exceptions."""

import asyncio
import gc
import logging
import threading
import time

from PySide6.QtWidgets import QApplication

from ui.native.xdg_portal import PortalTransport


class _ClosingBus:
    """A session bus whose in-flight call breaks when the bus disconnects."""

    def __init__(self) -> None:
        self.call_started = threading.Event()
        self.closed_calls = []
        self._disconnected: asyncio.Event | None = None

    async def call(self, message):
        self._disconnected = self._disconnected or asyncio.Event()
        self.call_started.set()
        try:
            await asyncio.wait_for(self._disconnected.wait(), 0.2)
        except asyncio.TimeoutError:
            self.closed_calls.append(message.path)
            return None
        raise BrokenPipeError(32, "Broken pipe")

    def disconnect(self) -> None:
        if self._disconnected is not None:
            self._disconnected.set()


def test_closing_right_after_close_session_logs_no_unretrieved_task(caplog) -> None:
    QApplication.instance() or QApplication([])
    transport = PortalTransport()
    bus = _ClosingBus()

    async def fake_bus():
        transport._bus = bus
        return bus

    transport._ensure_bus = fake_bus
    transport.close_session("/org/freedesktop/portal/desktop/session/1_1/ut")
    assert bus.call_started.wait(2)
    with caplog.at_level(logging.ERROR, logger="asyncio"):
        transport.close()
        time.sleep(0.05)
        gc.collect()
    assert "never retrieved" not in caplog.text
    # The pending Close reached the portal before the bus went away.
    assert bus.closed_calls == ["/org/freedesktop/portal/desktop/session/1_1/ut"]


def test_host_app_registration_sends_app_id_and_tolerates_old_portals() -> None:
    QApplication.instance() or QApplication([])
    transport = PortalTransport()
    sent = []

    class _Bus:
        def __init__(self, fail: bool) -> None:
            self.fail = fail

        async def call(self, message):
            sent.append(message)
            if self.fail:
                raise RuntimeError("No such interface")
            return None

    asyncio.run(transport._register_host_app(_Bus(fail=False)))
    message = sent[-1]
    assert message.interface == "org.freedesktop.host.portal.Registry"
    assert message.member == "Register" and message.signature == "sa{sv}"
    assert message.body == ["com.ultratranscribr.app", {}]
    asyncio.run(transport._register_host_app(_Bus(fail=True)))  # must not raise


def test_hung_portal_does_not_stall_shutdown_past_the_join_budget() -> None:
    QApplication.instance() or QApplication([])
    transport = PortalTransport()
    started = threading.Event()

    class _HungBus:
        async def call(self, message):
            started.set()
            await asyncio.Event().wait()  # the portal never answers

        def disconnect(self) -> None:
            pass

    bus = _HungBus()

    async def fake_bus():
        transport._bus = bus
        return bus

    transport._ensure_bus = fake_bus
    transport.close_session("/org/freedesktop/portal/desktop/session/1_1/hung")
    assert started.wait(2)
    began = time.monotonic()
    transport.close()
    assert time.monotonic() - began < 0.9
    assert not transport._thread.is_alive()


def test_many_open_requests_close_concurrently_within_budget() -> None:
    QApplication.instance() or QApplication([])
    transport = PortalTransport()

    class _HungBus:
        async def call(self, message):
            await asyncio.Event().wait()

        def disconnect(self) -> None:
            pass

    transport._bus = _HungBus()
    transport._active_request_paths = {
        f"r{i}": f"/org/freedesktop/portal/desktop/request/1_1/r{i}" for i in range(8)
    }

    loop = asyncio.new_event_loop()
    try:
        loop.create_task(transport._shutdown_worker())
        began = time.monotonic()
        loop.run_forever()  # the worker stops its own loop when done
        elapsed = time.monotonic() - began
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    finally:
        loop.close()
    assert elapsed < 0.6


def test_bus_is_disconnected_when_connection_setup_is_cancelled(monkeypatch) -> None:
    import ui.native.xdg_portal as portal

    QApplication.instance() or QApplication([])
    transport = PortalTransport()
    disconnected = []

    class _Bus:
        def add_message_handler(self, _handler) -> None:
            pass

        def disconnect(self) -> None:
            disconnected.append(True)

    class _MessageBus:
        def __init__(self, **_kwargs) -> None:
            pass

        async def connect(self):
            return _Bus()

    async def slow_match(*_args):
        return None

    async def hung_register(_bus):
        await asyncio.Event().wait()

    monkeypatch.setattr(portal, "MessageBus", _MessageBus)
    transport._dbus_match = slow_match
    transport._register_host_app = hung_register

    async def cancel_during_setup():
        task = asyncio.ensure_future(transport._connect_bus())
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(cancel_during_setup())
    assert disconnected == [True]
