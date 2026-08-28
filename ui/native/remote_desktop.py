"""Keyboard-only XDG RemoteDesktop portal used for paste injection."""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtDBus import QDBusInterface, QDBusMessage, QDBusObjectPath

from ui.native.xdg_portal import PORTAL_PATH, PORTAL_SERVICE, PortalClient, object_path, token

logger = logging.getLogger(__name__)
INTERFACE = "org.freedesktop.portal.RemoteDesktop"
KEYBOARD = 1
KEY_RELEASED = 0
KEY_PRESSED = 1
XK_SHIFT_L = 0xFFE1
XK_INSERT = 0xFF63


class RemoteDesktopKeyboardPortal(PortalClient):
    readyChanged = Signal(bool)
    errorOccurred = Signal(str)
    restoreTokenChanged = Signal(str)

    def __init__(self, restore_token: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self._session: str | None = None
        self._starting = False
        self._ready = False
        self._restore_token = str(restore_token or "")
        self._restore_attempted = False

    @property
    def ready(self) -> bool:
        return self._ready

    def ensure_ready(self) -> None:
        if self._ready or self._starting:
            return
        self._starting = True
        self._restore_attempted = bool(self._restore_token)
        try:
            self.call_request(
                INTERFACE,
                "CreateSession",
                {
                    "handle_token": token("ut_rd_request"),
                    "session_handle_token": token("ut_rd_session"),
                },
                callback=self._created,
            )
        except Exception as exc:
            self._fail(exc)

    def _created(self, response: int, results: dict[str, Any]) -> None:
        if response != 0:
            self._fail(RuntimeError(f"Creazione RemoteDesktop rifiutata ({response})"))
            return
        self._session = object_path(results.get("session_handle"))
        if not self._session:
            self._fail(RuntimeError("RemoteDesktop non ha restituito una sessione"))
            return
        options: dict[str, Any] = {
            "handle_token": token("ut_rd_devices"),
            "types": KEYBOARD,
            "persist_mode": 2,
        }
        if self._restore_token:
            options["restore_token"] = self._restore_token
        try:
            self.call_request(
                INTERFACE,
                "SelectDevices",
                QDBusObjectPath(self._session),
                options,
                callback=self._selected,
            )
        except Exception as exc:
            self._fail(exc)

    def _selected(self, response: int, _results: dict[str, Any]) -> None:
        if response != 0:
            self._fail(RuntimeError(f"Permesso tastiera RemoteDesktop rifiutato ({response})"))
            return
        assert self._session
        try:
            self.call_request(
                INTERFACE,
                "Start",
                QDBusObjectPath(self._session),
                "",
                {"handle_token": token("ut_rd_start")},
                callback=self._started,
            )
        except Exception as exc:
            self._fail(exc)

    def _started(self, response: int, results: dict[str, Any]) -> None:
        self._starting = False
        if response != 0:
            self._fail(RuntimeError(f"Avvio RemoteDesktop rifiutato ({response})"))
            return
        devices = int(results.get("devices", 0) or 0)
        if devices != KEYBOARD:
            self._fail(
                RuntimeError(
                    f"RemoteDesktop deve concedere solo la tastiera; dispositivi ricevuti: {devices}"
                )
            )
            return
        returned_token = str(results.get("restore_token") or "")
        if returned_token and returned_token != self._restore_token:
            self._restore_token = returned_token
            self.restoreTokenChanged.emit(returned_token)
        self._restore_attempted = False
        self._ready = True
        self.readyChanged.emit(True)

    def paste_shortcut(self) -> bool:
        if not self._ready or not self._session:
            self.ensure_ready()
            return False
        try:
            self._notify_keysym(XK_SHIFT_L, KEY_PRESSED)
            self._notify_keysym(XK_INSERT, KEY_PRESSED)
            self._notify_keysym(XK_INSERT, KEY_RELEASED)
            self._notify_keysym(XK_SHIFT_L, KEY_RELEASED)
            return True
        except Exception as exc:
            self._fail(exc)
            return False

    def _notify_keysym(self, keysym: int, state: int) -> None:
        assert self._session
        self._require_bus()
        interface = QDBusInterface(
            PORTAL_SERVICE,
            PORTAL_PATH,
            INTERFACE,
            self.bus,
        )
        reply = interface.call(
            "NotifyKeyboardKeysym",
            QDBusObjectPath(self._session),
            {},
            int(keysym),
            int(state),
        )
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            raise RuntimeError(
                f"Invio tasto RemoteDesktop fallito: {reply.errorMessage()}"
            )

    def reset(self) -> None:
        self.close_requests()
        self.close_session(self._session)
        self._session = None
        self._starting = False
        if self._ready:
            self._ready = False
            self.readyChanged.emit(False)

    def close(self) -> None:
        self.reset()

    def _fail(self, exc: Exception) -> None:
        logger.error("RemoteDesktop portal: %s", exc)
        if self._restore_attempted and self._restore_token:
            self._restore_token = ""
            self._restore_attempted = False
            self.restoreTokenChanged.emit("")
        self.reset()
        self.errorOccurred.emit(str(exc))
