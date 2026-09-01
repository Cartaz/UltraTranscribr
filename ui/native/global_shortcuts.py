"""XDG GlobalShortcuts adapter for dictation activation on Wayland."""
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
)

logger = logging.getLogger(__name__)
INTERFACE = "org.freedesktop.portal.GlobalShortcuts"
SHORTCUT_ID = "dictation"


class GlobalShortcutsPortal(PortalClient):
    pressed = Signal()
    released = Signal()
    readyChanged = Signal(bool)
    errorOccurred = Signal(str)

    def __init__(
        self,
        transport: PortalTransport | None = None,
        parent=None,
    ) -> None:
        super().__init__(transport, parent)
        self._session: str | None = None
        self._ready = False
        self._starting = False
        self._activated_subscription: str | None = None
        self._deactivated_subscription: str | None = None

    @property
    def ready(self) -> bool:
        return self._ready

    def start(self) -> None:
        if self._ready or self._starting:
            return
        self._starting = True
        handle = token("ut_gs_request")
        self.call_request(
            INTERFACE,
            "CreateSession",
            "a{sv}",
            [{
                "handle_token": string_variant(handle),
                "session_handle_token": string_variant(token("ut_gs_session")),
            }],
            handle_token=handle,
            callback=self._created,
            error_callback=self._fail,
        )

    def _created(self, response: int, results: dict[str, Any]) -> None:
        if response != 0:
            self._fail(RuntimeError(f"Creazione GlobalShortcuts rifiutata ({response})"))
            return
        self._session = object_path(results.get("session_handle"))
        if not self._session:
            self._fail(RuntimeError("GlobalShortcuts non ha restituito una sessione"))
            return
        self._connect_signals()
        handle = token("ut_gs_bind")
        shortcuts = [[
            SHORTCUT_ID,
            {"description": string_variant("Avvia o termina la dettatura globale")},
        ]]
        self.call_request(
            INTERFACE,
            "BindShortcuts",
            "oa(sa{sv})sa{sv}",
            [
                self._session,
                shortcuts,
                "",
                {"handle_token": string_variant(handle)},
            ],
            handle_token=handle,
            callback=self._bound,
            error_callback=self._fail,
        )

    def _bound(self, response: int, _results: dict[str, Any]) -> None:
        self._starting = False
        if response != 0:
            self._fail(RuntimeError(f"Binding hotkey globale rifiutato ({response})"))
            return
        self._ready = True
        self.readyChanged.emit(True)

    def _connect_signals(self) -> None:
        if self._activated_subscription or self._deactivated_subscription:
            return
        self._activated_subscription = self.subscribe_signal(
            INTERFACE,
            "Activated",
            self._activated,
        )
        self._deactivated_subscription = self.subscribe_signal(
            INTERFACE,
            "Deactivated",
            self._deactivated,
        )

    def _activated(self, body: list[Any]) -> None:
        if len(body) < 2:
            return
        session = object_path(body[0])
        shortcut_id = str(body[1] or "")
        if shortcut_id == SHORTCUT_ID and session == self._session:
            self.pressed.emit()

    def _deactivated(self, body: list[Any]) -> None:
        if len(body) < 2:
            return
        session = object_path(body[0])
        shortcut_id = str(body[1] or "")
        if shortcut_id == SHORTCUT_ID and session == self._session:
            self.released.emit()

    def close(self) -> None:
        self._reset()
        self.close_owned_transport()

    def _reset(self) -> None:
        """Release every resource that may exist after a partial portal startup."""
        self.close_requests()
        self.unsubscribe_signal(self._activated_subscription)
        self.unsubscribe_signal(self._deactivated_subscription)
        self._activated_subscription = None
        self._deactivated_subscription = None
        self.close_session(self._session)
        self._session = None
        self._starting = False
        if self._ready:
            self._ready = False
            self.readyChanged.emit(False)

    def _fail(self, exc: Exception) -> None:
        logger.error("GlobalShortcuts portal: %s", exc)
        self._reset()
        self.errorOccurred.emit(str(exc))
