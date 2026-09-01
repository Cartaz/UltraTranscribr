"""Keyboard-only XDG RemoteDesktop portal used for paste injection."""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Signal

from ui.native.xdg_portal import (
    PortalClient,
    PortalTransport,
    object_path,
    string_variant,
    token,
    uint_variant,
)

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
    pasteCompleted = Signal()

    def __init__(
        self,
        restore_token: str | None = None,
        transport: PortalTransport | None = None,
        parent=None,
    ) -> None:
        super().__init__(transport, parent)
        self._session: str | None = None
        self._starting = False
        self._ready = False
        self._restore_token = str(restore_token or "")
        self._restore_attempted = False
        self._paste_in_flight = False
        self._paste_generation = 0

    @property
    def ready(self) -> bool:
        return self._ready

    def ensure_ready(self) -> None:
        if self._ready or self._starting:
            return
        self._starting = True
        self._restore_attempted = bool(self._restore_token)
        handle = token("ut_rd_request")
        self.call_request(
            INTERFACE,
            "CreateSession",
            "a{sv}",
            [{
                "handle_token": string_variant(handle),
                "session_handle_token": string_variant(token("ut_rd_session")),
            }],
            handle_token=handle,
            callback=self._created,
            error_callback=self._fail,
        )

    def _created(self, response: int, results: dict[str, Any]) -> None:
        if response != 0:
            self._fail(RuntimeError(f"Creazione RemoteDesktop rifiutata ({response})"))
            return
        self._session = object_path(results.get("session_handle"))
        if not self._session:
            self._fail(RuntimeError("RemoteDesktop non ha restituito una sessione"))
            return
        handle = token("ut_rd_devices")
        options: dict[str, Any] = {
            "handle_token": string_variant(handle),
            "types": uint_variant(KEYBOARD),
            "persist_mode": uint_variant(2),
        }
        if self._restore_token:
            options["restore_token"] = string_variant(self._restore_token)
        self.call_request(
            INTERFACE,
            "SelectDevices",
            "oa{sv}",
            [self._session, options],
            handle_token=handle,
            callback=self._selected,
            error_callback=self._fail,
        )

    def _selected(self, response: int, _results: dict[str, Any]) -> None:
        if response != 0:
            self._fail(RuntimeError(f"Permesso tastiera RemoteDesktop rifiutato ({response})"))
            return
        if not self._session:
            self._fail(RuntimeError("Sessione RemoteDesktop assente prima di Start"))
            return
        handle = token("ut_rd_start")
        self.call_request(
            INTERFACE,
            "Start",
            "osa{sv}",
            [
                self._session,
                "",
                {"handle_token": string_variant(handle)},
            ],
            handle_token=handle,
            callback=self._started,
            error_callback=self._fail,
        )

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
        if not self._ready or not self._session or self._paste_in_flight:
            if not self._ready:
                self.ensure_ready()
            return False
        self._paste_in_flight = True
        self._paste_generation += 1
        generation = self._paste_generation
        session = self._session
        calls = [
            ("NotifyKeyboardKeysym", "oa{sv}iu", [session, {}, XK_SHIFT_L, KEY_PRESSED]),
            ("NotifyKeyboardKeysym", "oa{sv}iu", [session, {}, XK_INSERT, KEY_PRESSED]),
            ("NotifyKeyboardKeysym", "oa{sv}iu", [session, {}, XK_INSERT, KEY_RELEASED]),
            ("NotifyKeyboardKeysym", "oa{sv}iu", [session, {}, XK_SHIFT_L, KEY_RELEASED]),
        ]

        def completed(error: str | None) -> None:
            if generation != self._paste_generation:
                return
            self._paste_in_flight = False
            if error:
                self._fail(RuntimeError(f"Invio tasto RemoteDesktop fallito: {error}"))
                return
            self.pasteCompleted.emit()

        self.call_sequence(INTERFACE, calls, completed)
        return True

    def reset(self) -> None:
        self.close_requests()
        self.close_session(self._session)
        self._session = None
        self._starting = False
        self._paste_generation += 1
        self._paste_in_flight = False
        if self._ready:
            self._ready = False
            self.readyChanged.emit(False)

    def close(self) -> None:
        self.reset()
        self.close_owned_transport()

    def _fail(self, exc: Exception) -> None:
        logger.error("RemoteDesktop portal: %s", exc)
        if self._restore_attempted and self._restore_token:
            self._restore_token = ""
            self._restore_attempted = False
            self.restoreTokenChanged.emit("")
        self.reset()
        self.errorOccurred.emit(str(exc))
