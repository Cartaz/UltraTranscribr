"""Typed, non-blocking XDG Desktop Portal transport for native dictation."""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections.abc import Callable, Sequence
from typing import Any

from dbus_next import BusType, Message, MessageType, Variant
from dbus_next.aio import MessageBus
from PySide6.QtCore import QObject, Signal, Slot

logger = logging.getLogger(__name__)
PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"
SESSION_INTERFACE = "org.freedesktop.portal.Session"
REQUEST_PATH_PREFIX = "/org/freedesktop/portal/desktop/request/"
_DBUS_SERVICE = "org.freedesktop.DBus"
_DBUS_PATH = "/org/freedesktop/DBus"
_DBUS_INTERFACE = "org.freedesktop.DBus"
_REQUEST_TIMEOUT_S = 60.0
_MAX_EARLY_RESPONSES = 64

ResponseCallback = Callable[[int, dict[str, Any]], None]
ErrorCallback = Callable[[Exception], None]
SequenceCallback = Callable[[str | None], None]
SignalCallback = Callable[[list[Any]], None]
PortalCall = tuple[str, str, list[Any]]


def token(prefix: str) -> str:
    safe = "".join(ch for ch in prefix if ch.isalnum() or ch == "_") or "ut"
    return f"{safe}_{uuid.uuid4().hex}"


def unwrap(value: Any) -> Any:
    if isinstance(value, Variant):
        return unwrap(value.value)
    if isinstance(value, dict):
        return {str(key): unwrap(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [unwrap(item) for item in value]
    return value


def object_path(value: Any) -> str:
    return str(unwrap(value) or "")


def predicted_request_path(unique_name: str, handle_token: str) -> str:
    """Return the XDG request path derived from a bus unique name and token."""
    sender = str(unique_name or "")
    if not sender.startswith(":"):
        raise RuntimeError("Nome univoco D-Bus di sessione non disponibile")
    clean_token = str(handle_token or "")
    if not clean_token:
        raise ValueError("handle_token portal mancante")
    sender_component = sender[1:].replace(".", "_")
    return f"{REQUEST_PATH_PREFIX}{sender_component}/{clean_token}"


def string_variant(value: str) -> Variant:
    return Variant("s", str(value))


def uint_variant(value: int) -> Variant:
    number = int(value)
    if not 0 <= number <= 0xFFFFFFFF:
        raise ValueError("Valore D-Bus uint32 fuori intervallo")
    return Variant("u", number)


class PortalTransport(QObject):
    """Own one dbus-next session connection on one background asyncio thread."""

    _requestCompleted = Signal(str, int, object)
    _requestFailed = Signal(str, str)
    _sequenceCompleted = Signal(str, str)
    _signalArrived = Signal(str, str, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._pending: list[Callable[[], Any]] = []
        self._closed = False

        self._request_callbacks: dict[str, tuple[ResponseCallback, ErrorCallback]] = {}
        self._sequence_callbacks: dict[str, SequenceCallback] = {}
        self._signal_callbacks: dict[tuple[str, str], dict[str, SignalCallback]] = {}

        self._bus: MessageBus | None = None
        self._bus_task: asyncio.Task[MessageBus] | None = None
        self._request_waiters: dict[str, tuple[str, asyncio.Future[tuple[int, dict[str, Any]]]]] = {}
        self._active_request_paths: dict[str, str] = {}
        self._cancelled_requests: set[str] = set()
        self._early_responses: dict[str, tuple[int, dict[str, Any]]] = {}

        self._requestCompleted.connect(self._deliver_request)
        self._requestFailed.connect(self._deliver_request_error)
        self._sequenceCompleted.connect(self._deliver_sequence)
        self._signalArrived.connect(self._deliver_signal)

    def call_request(
        self,
        interface_name: str,
        method: str,
        signature: str,
        body: list[Any],
        *,
        handle_token: str,
        callback: ResponseCallback,
        error_callback: ErrorCallback,
    ) -> str:
        request_id = uuid.uuid4().hex
        self._request_callbacks[request_id] = (callback, error_callback)
        self._schedule(
            lambda: self._run_request(
                request_id,
                str(interface_name),
                str(method),
                str(signature),
                list(body),
                str(handle_token),
            ),
            lambda message: self._requestFailed.emit(request_id, message),
        )
        return request_id

    def cancel_request(self, request_id: str) -> None:
        request_key = str(request_id or "")
        self._request_callbacks.pop(request_key, None)
        if request_key:
            self._schedule(
                lambda: self._cancel_request(request_key),
                lambda _message: None,
            )

    def call_sequence(
        self,
        interface_name: str,
        calls: Sequence[PortalCall],
        callback: SequenceCallback,
    ) -> str:
        sequence_id = uuid.uuid4().hex
        self._sequence_callbacks[sequence_id] = callback
        frozen_calls = [(str(member), str(signature), list(body)) for member, signature, body in calls]
        self._schedule(
            lambda: self._run_sequence(sequence_id, str(interface_name), frozen_calls),
            lambda message: self._sequenceCompleted.emit(sequence_id, message),
        )
        return sequence_id

    def close_session(self, session_handle: str | None) -> None:
        path = str(session_handle or "")
        if not path:
            return
        self._schedule(
            lambda: self._close_object(path, SESSION_INTERFACE),
            lambda message: logger.warning("Chiusura sessione portal fallita: %s", message),
        )

    def subscribe_portal_signal(
        self,
        interface_name: str,
        member: str,
        callback: SignalCallback,
    ) -> str:
        subscription_id = uuid.uuid4().hex
        key = (str(interface_name), str(member))
        self._signal_callbacks.setdefault(key, {})[subscription_id] = callback
        return subscription_id

    def unsubscribe_portal_signal(self, subscription_id: str) -> None:
        target = str(subscription_id or "")
        for callbacks in self._signal_callbacks.values():
            callbacks.pop(target, None)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            loop = self._loop
            self._pending = []
        self._request_callbacks.clear()
        self._sequence_callbacks.clear()
        self._signal_callbacks.clear()
        if loop is not None:
            loop.call_soon_threadsafe(lambda: asyncio.create_task(self._shutdown_worker()))
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
            if thread.is_alive():
                logger.warning("Worker XDG portal non terminato entro il timeout")

    def _schedule(
        self,
        factory: Callable[[], Any],
        on_rejected: Callable[[str], None],
    ) -> None:
        with self._lock:
            if self._closed:
                on_rejected("Transport XDG portal chiuso")
                return
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._thread_main,
                    name="DictationPortalDBus",
                    daemon=True,
                )
                self._thread.start()
            loop = self._loop
            if loop is None:
                self._pending.append(lambda: self._start_task(factory, on_rejected))
                return
        loop.call_soon_threadsafe(self._start_task, factory, on_rejected)

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            if self._closed:
                loop.close()
                return
            self._loop = loop
            pending = self._pending
            self._pending = []
        for starter in pending:
            loop.call_soon(starter)
        try:
            loop.run_forever()
        finally:
            pending_tasks = asyncio.all_tasks(loop)
            for task in pending_tasks:
                task.cancel()
            if pending_tasks:
                loop.run_until_complete(asyncio.gather(*pending_tasks, return_exceptions=True))
            loop.close()
            with self._lock:
                self._loop = None

    @staticmethod
    def _start_task(factory: Callable[[], Any], on_rejected: Callable[[str], None]) -> None:
        try:
            coroutine = factory()
            task = asyncio.create_task(coroutine)
        except Exception as exc:
            on_rejected(str(exc))
            return

        def done(completed: asyncio.Task) -> None:
            if completed.cancelled():
                return
            try:
                completed.result()
            except Exception as exc:
                on_rejected(str(exc))

        task.add_done_callback(done)

    async def _ensure_bus(self) -> MessageBus:
        if self._bus is not None:
            return self._bus
        if self._bus_task is None:
            self._bus_task = asyncio.create_task(self._connect_bus())
        try:
            return await self._bus_task
        finally:
            if self._bus is None and self._bus_task and self._bus_task.done():
                self._bus_task = None

    async def _connect_bus(self) -> MessageBus:
        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        try:
            bus.add_message_handler(self._on_message)
            for rule in (
                "type='signal',path_namespace='/org/freedesktop/portal/desktop/request',"
                "interface='org.freedesktop.portal.Request',member='Response'",
                "type='signal',path='/org/freedesktop/portal/desktop',"
                "interface='org.freedesktop.portal.GlobalShortcuts',member='Activated'",
                "type='signal',path='/org/freedesktop/portal/desktop',"
                "interface='org.freedesktop.portal.GlobalShortcuts',member='Deactivated'",
            ):
                await self._dbus_match(bus, "AddMatch", rule)
        except Exception:
            bus.disconnect()
            raise
        self._bus = bus
        return bus

    async def _dbus_match(self, bus: MessageBus, member: str, rule: str) -> None:
        reply = await bus.call(
            Message(
                destination=_DBUS_SERVICE,
                path=_DBUS_PATH,
                interface=_DBUS_INTERFACE,
                member=member,
                signature="s",
                body=[rule],
            )
        )
        self._raise_for_error(reply, f"D-Bus {member}")

    def _on_message(self, message: Message) -> None:
        if message.message_type != MessageType.SIGNAL:
            return
        if message.interface == REQUEST_INTERFACE and message.member == "Response":
            path = str(message.path or "")
            if len(message.body) < 2:
                return
            payload = (int(message.body[0]), unwrap(message.body[1]))
            waiter = self._request_waiters.get(path)
            if waiter is not None:
                _request_id, future = waiter
                if not future.done():
                    future.set_result(payload)
            else:
                self._early_responses[path] = payload
                while len(self._early_responses) > _MAX_EARLY_RESPONSES:
                    self._early_responses.pop(next(iter(self._early_responses)))
            return
        if message.path == PORTAL_PATH and message.interface and message.member:
            self._signalArrived.emit(
                str(message.interface),
                str(message.member),
                unwrap(message.body),
            )

    async def _run_request(
        self,
        request_id: str,
        interface_name: str,
        method: str,
        signature: str,
        body: list[Any],
        handle_token: str,
    ) -> None:
        bus = await self._ensure_bus()
        unique_name = str(bus.unique_name or "")
        predicted_path = predicted_request_path(unique_name, handle_token)
        loop = asyncio.get_running_loop()
        response_future: asyncio.Future[tuple[int, dict[str, Any]]] = loop.create_future()
        self._request_waiters[predicted_path] = (request_id, response_future)
        self._active_request_paths[request_id] = predicted_path
        early = self._early_responses.pop(predicted_path, None)
        if early is not None:
            response_future.set_result(early)

        try:
            reply = await bus.call(
                Message(
                    destination=PORTAL_SERVICE,
                    path=PORTAL_PATH,
                    interface=interface_name,
                    member=method,
                    signature=signature,
                    body=body,
                )
            )
            self._raise_for_error(reply, f"Portal {method}")
            if not reply.body:
                raise RuntimeError(f"Portal {method} non ha restituito il request handle")
            returned_path = object_path(reply.body[0])
            if not returned_path.startswith(REQUEST_PATH_PREFIX):
                raise RuntimeError(f"Request handle portal non valido: {returned_path}")
            if returned_path != predicted_path and not response_future.done():
                self._request_waiters.pop(predicted_path, None)
                self._request_waiters[returned_path] = (request_id, response_future)
                self._active_request_paths[request_id] = returned_path
                early = self._early_responses.pop(returned_path, None)
                if early is not None:
                    response_future.set_result(early)

            response, results = await asyncio.wait_for(response_future, timeout=_REQUEST_TIMEOUT_S)
            if request_id not in self._cancelled_requests:
                self._requestCompleted.emit(request_id, response, results)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if request_id not in self._cancelled_requests:
                self._requestFailed.emit(request_id, str(exc))
        finally:
            path = self._active_request_paths.pop(request_id, None)
            if path:
                current = self._request_waiters.get(path)
                if current and current[0] == request_id:
                    self._request_waiters.pop(path, None)
            self._cancelled_requests.discard(request_id)

    async def _cancel_request(self, request_id: str) -> None:
        self._cancelled_requests.add(request_id)
        path = self._active_request_paths.pop(request_id, None)
        if not path:
            return
        waiter = self._request_waiters.pop(path, None)
        if waiter is not None:
            future = waiter[1]
            if not future.done():
                future.cancel()
        try:
            await self._close_object(path, REQUEST_INTERFACE)
        except Exception:
            logger.debug("Request portal già chiusa o non raggiungibile: %s", path, exc_info=True)

    async def _run_sequence(
        self,
        sequence_id: str,
        interface_name: str,
        calls: Sequence[PortalCall],
    ) -> None:
        try:
            bus = await self._ensure_bus()
            for member, signature, body in calls:
                reply = await bus.call(
                    Message(
                        destination=PORTAL_SERVICE,
                        path=PORTAL_PATH,
                        interface=interface_name,
                        member=member,
                        signature=signature,
                        body=body,
                    )
                )
                self._raise_for_error(reply, f"Portal {member}")
            self._sequenceCompleted.emit(sequence_id, "")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._sequenceCompleted.emit(sequence_id, str(exc))

    async def _close_object(self, path: str, interface_name: str) -> None:
        bus = await self._ensure_bus()
        reply = await bus.call(
            Message(
                destination=PORTAL_SERVICE,
                path=path,
                interface=interface_name,
                member="Close",
            )
        )
        self._raise_for_error(reply, f"Portal Close {path}")

    async def _shutdown_worker(self) -> None:
        paths = list(self._active_request_paths.values())
        self._active_request_paths.clear()
        for _path, (_request_id, future) in list(self._request_waiters.items()):
            if not future.done():
                future.cancel()
        self._request_waiters.clear()
        for path in paths:
            try:
                await self._close_object(path, REQUEST_INTERFACE)
            except Exception:
                logger.debug("Chiusura request portal durante shutdown fallita", exc_info=True)
        if self._bus is not None:
            try:
                self._bus.disconnect()
            except Exception:
                logger.debug("Disconnessione bus XDG portal fallita", exc_info=True)
            self._bus = None
        loop = asyncio.get_running_loop()
        loop.call_soon(loop.stop)

    @staticmethod
    def _raise_for_error(reply: Message | None, operation: str) -> None:
        if reply is None:
            raise RuntimeError(f"{operation} non ha restituito una risposta D-Bus")
        if reply.message_type == MessageType.ERROR:
            detail = str(reply.body[0]) if reply.body else str(reply.error_name or "errore D-Bus")
            raise RuntimeError(f"{operation} fallito: {detail}")

    @Slot(str, int, object)
    def _deliver_request(self, request_id: str, response: int, results: Any) -> None:
        callbacks = self._request_callbacks.pop(request_id, None)
        if callbacks is not None:
            callback, _error_callback = callbacks
            callback(int(response), dict(results or {}))

    @Slot(str, str)
    def _deliver_request_error(self, request_id: str, message: str) -> None:
        callbacks = self._request_callbacks.pop(request_id, None)
        if callbacks is not None:
            _callback, error_callback = callbacks
            error_callback(RuntimeError(str(message)))

    @Slot(str, str)
    def _deliver_sequence(self, sequence_id: str, message: str) -> None:
        callback = self._sequence_callbacks.pop(sequence_id, None)
        if callback is not None:
            callback(str(message) or None)

    @Slot(str, str, object)
    def _deliver_signal(self, interface_name: str, member: str, body: Any) -> None:
        callbacks = tuple(self._signal_callbacks.get((interface_name, member), {}).values())
        payload = list(body or [])
        for callback in callbacks:
            callback(payload)


class PortalClient(QObject):
    """Common request/session lifecycle without portal-specific policy."""

    def __init__(
        self,
        transport: PortalTransport | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._transport = transport or PortalTransport(self)
        self._owns_transport = transport is None
        self._requests: set[str] = set()
        self._subscriptions: set[str] = set()

    def call_request(
        self,
        interface_name: str,
        method: str,
        signature: str,
        body: list[Any],
        *,
        handle_token: str,
        callback: ResponseCallback,
        error_callback: ErrorCallback,
    ) -> None:
        request_id = ""

        def completed(response: int, results: dict[str, Any]) -> None:
            if request_id:
                self._requests.discard(request_id)
            callback(response, results)

        def failed(exc: Exception) -> None:
            if request_id:
                self._requests.discard(request_id)
            error_callback(exc)

        request_id = self._transport.call_request(
            interface_name,
            method,
            signature,
            body,
            handle_token=handle_token,
            callback=completed,
            error_callback=failed,
        )
        self._requests.add(request_id)

    def call_sequence(
        self,
        interface_name: str,
        calls: Sequence[PortalCall],
        callback: SequenceCallback,
    ) -> str:
        return self._transport.call_sequence(interface_name, calls, callback)

    def subscribe_signal(
        self,
        interface_name: str,
        member: str,
        callback: SignalCallback,
    ) -> str:
        subscription_id = self._transport.subscribe_portal_signal(interface_name, member, callback)
        self._subscriptions.add(subscription_id)
        return subscription_id

    def unsubscribe_signal(self, subscription_id: str | None) -> None:
        if not subscription_id:
            return
        self._subscriptions.discard(subscription_id)
        self._transport.unsubscribe_portal_signal(subscription_id)

    def close_session(self, session_handle: str | None) -> None:
        self._transport.close_session(session_handle)

    def close_requests(self) -> None:
        requests = list(self._requests)
        self._requests.clear()
        for request_id in requests:
            self._transport.cancel_request(request_id)

    def close_subscriptions(self) -> None:
        subscriptions = list(self._subscriptions)
        self._subscriptions.clear()
        for subscription_id in subscriptions:
            self._transport.unsubscribe_portal_signal(subscription_id)

    def close_owned_transport(self) -> None:
        if self._owns_transport:
            self._transport.close()
