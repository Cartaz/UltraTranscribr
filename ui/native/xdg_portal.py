"""Small QtDBus helpers shared by XDG Desktop Portal adapters."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from PySide6.QtCore import QObject, SLOT, Slot
from PySide6.QtDBus import (
    QDBusConnection,
    QDBusInterface,
    QDBusMessage,
    QDBusObjectPath,
    QDBusVariant,
)

logger = logging.getLogger(__name__)
PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"
SESSION_INTERFACE = "org.freedesktop.portal.Session"
REQUEST_PATH_PREFIX = "/org/freedesktop/portal/desktop/request/"
_RESPONSE_DBUS_SIGNATURE = "ua{sv}"
_RESPONSE_SLOT = SLOT("_response(uint,QVariantMap)")
ResponseCallback = Callable[[int, dict[str, Any]], None]


def token(prefix: str) -> str:
    safe = "".join(ch for ch in prefix if ch.isalnum() or ch == "_") or "ut"
    return f"{safe}_{uuid.uuid4().hex}"


def unwrap(value: Any) -> Any:
    if isinstance(value, QDBusVariant):
        return unwrap(value.variant())
    if isinstance(value, QDBusObjectPath):
        return value.path()
    if isinstance(value, dict):
        return {str(key): unwrap(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [unwrap(item) for item in value]
    return value


def object_path(value: Any) -> str:
    item = unwrap(value)
    return str(item or "")


def predicted_request_path(bus: QDBusConnection, handle_token: str) -> str:
    """Return the portal Request path prescribed for this connection/token.

    XDG portals may emit ``Request.Response`` immediately. Subscribing to this
    predictable path before issuing the method call prevents losing that signal.
    """
    sender = str(bus.baseService() or "")
    if not sender.startswith(":"):
        raise RuntimeError("Nome univoco D-Bus di sessione non disponibile")
    sender_component = sender[1:].replace(".", "_")
    clean_token = str(handle_token or "")
    if not clean_token:
        raise ValueError("handle_token portal mancante")
    return f"{REQUEST_PATH_PREFIX}{sender_component}/{clean_token}"


def _handle_token(args: tuple[Any, ...]) -> str:
    if not args or not isinstance(args[-1], dict):
        raise ValueError("La richiesta portal deve terminare con options a{sv}")
    value = args[-1].get("handle_token")
    result = str(unwrap(value) or "")
    if not result:
        raise ValueError("options.handle_token portal mancante")
    return result


class PortalRequest(QObject):
    """Own one org.freedesktop.portal.Request response subscription."""

    def __init__(
        self,
        bus: QDBusConnection,
        path: str,
        callback: ResponseCallback,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        self._path = path
        self._callback = callback
        self._done = False
        self._connect()

    def _connect(self) -> None:
        ok = self._bus.connect(
            PORTAL_SERVICE,
            self._path,
            REQUEST_INTERFACE,
            "Response",
            _RESPONSE_DBUS_SIGNATURE,
            self,
            _RESPONSE_SLOT,
        )
        if not ok:
            raise RuntimeError(f"Impossibile ascoltare la risposta portal {self._path}")

    def rebind(self, path: str) -> None:
        """Move the subscription if a portal returns a non-predicted handle."""
        if self._done or path == self._path:
            return
        self._disconnect()
        self._path = path
        self._connect()

    @Slot("uint", "QVariantMap")
    def _response(self, response: int, results: dict) -> None:
        if self._done:
            return
        self._done = True
        self._disconnect()
        self._callback(int(response), unwrap(results))
        self.deleteLater()

    def close(self) -> None:
        if self._done:
            return
        self._done = True
        self._disconnect()
        interface = QDBusInterface(
            PORTAL_SERVICE,
            self._path,
            REQUEST_INTERFACE,
            self._bus,
        )
        interface.call("Close")
        self.deleteLater()

    def _disconnect(self) -> None:
        self._bus.disconnect(
            PORTAL_SERVICE,
            self._path,
            REQUEST_INTERFACE,
            "Response",
            _RESPONSE_DBUS_SIGNATURE,
            self,
            _RESPONSE_SLOT,
        )


class PortalClient(QObject):
    """Common request/session lifecycle without portal-specific policy."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.bus = QDBusConnection.sessionBus()
        self._requests: set[PortalRequest] = set()

    def _require_bus(self) -> None:
        if not self.bus.isConnected():
            raise RuntimeError("Bus D-Bus di sessione non disponibile")

    def call_request(
        self,
        interface_name: str,
        method: str,
        *args: Any,
        callback: ResponseCallback,
    ) -> None:
        self._require_bus()
        handle_token = _handle_token(args)
        predicted_path = predicted_request_path(self.bus, handle_token)
        request_ref: PortalRequest | None = None

        def completed(response: int, results: dict[str, Any]) -> None:
            if request_ref is not None:
                self._requests.discard(request_ref)
            callback(response, results)

        # Subscribe before the portal method call: Response may otherwise race
        # the caller between the method reply and signal subscription.
        request_ref = PortalRequest(self.bus, predicted_path, completed, self)
        self._requests.add(request_ref)
        try:
            interface = QDBusInterface(
                PORTAL_SERVICE,
                PORTAL_PATH,
                interface_name,
                self.bus,
            )
            message = interface.call(method, *args)
            if message.type() == QDBusMessage.MessageType.ErrorMessage:
                raise RuntimeError(f"Portal {method} fallito: {message.errorMessage()}")
            arguments = message.arguments()
            if not arguments:
                raise RuntimeError(f"Portal {method} non ha restituito il request handle")
            returned_path = object_path(arguments[0])
            if not returned_path.startswith(REQUEST_PATH_PREFIX):
                raise RuntimeError(f"Request handle portal non valido: {returned_path}")
            request_ref.rebind(returned_path)
        except Exception:
            self._requests.discard(request_ref)
            request_ref.close()
            raise

    def close_session(self, session_handle: str | None) -> None:
        if not session_handle or not self.bus.isConnected():
            return
        interface = QDBusInterface(
            PORTAL_SERVICE,
            session_handle,
            SESSION_INTERFACE,
            self.bus,
        )
        interface.call("Close")

    def close_requests(self) -> None:
        requests = list(self._requests)
        self._requests.clear()
        for request in requests:
            try:
                request.close()
            except Exception:
                logger.exception("Chiusura request XDG portal fallita")
