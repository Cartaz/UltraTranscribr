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
