"""XDG GlobalShortcuts adapter for dictation activation on Wayland."""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import SLOT, Signal, Slot
from PySide6.QtDBus import QDBusObjectPath

from ui.native.xdg_portal import PORTAL_PATH, PORTAL_SERVICE, PortalClient, object_path, token

logger = logging.getLogger(__name__)
INTERFACE = "org.freedesktop.portal.GlobalShortcuts"
SHORTCUT_ID = "dictation"
_SHORTCUT_SIGNAL_SIGNATURE = "osta{sv}"
_ACTIVATED_SLOT = SLOT("_activated(QDBusObjectPath,QString,qulonglong,QVariantMap)")
_DEACTIVATED_SLOT = SLOT("_deactivated(QDBusObjectPath,QString,qulonglong,QVariantMap)")


class GlobalShortcutsPortal(PortalClient):
    pressed = Signal()
    released = Signal()
    readyChanged = Signal(bool)
    errorOccurred = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session: str | None = None
        self._ready = False
        self._starting = False
        self._signals_connected = False

    @property
    def ready(self) -> bool:
        return self._ready

    def start(self) -> None:
        if self._ready or self._starting:
            return
        self._starting = True
        try:
            self.call_request(
                INTERFACE,
                "CreateSession",
                {
                    "handle_token": token("ut_gs_request"),
                    "session_handle_token": token("ut_gs_session"),
                },
                callback=self._created,
            )
        except Exception as exc:
            self._fail(exc)

    def _created(self, response: int, results: dict[str, Any]) -> None:
        if response != 0:
            self._fail(RuntimeError(f"Creazione GlobalShortcuts rifiutata ({response})"))
            return
        self._session = object_path(results.get("session_handle"))
        if not self._session:
            self._fail(RuntimeError("GlobalShortcuts non ha restituito una sessione"))
            return
        try:
            self._connect_signals()
            self.call_request(
                INTERFACE,
                "BindShortcuts",
                QDBusObjectPath(self._session),
                [
                    (
                        SHORTCUT_ID,
                        {"description": "Avvia o termina la dettatura globale"},
                    )
                ],
                "",
                {"handle_token": token("ut_gs_bind")},
                callback=self._bound,
            )
        except Exception as exc:
            self._fail(exc)

    def _bound(self, response: int, _results: dict[str, Any]) -> None:
        self._starting = False
        if response != 0:
            self._fail(RuntimeError(f"Binding hotkey globale rifiutato ({response})"))
            return
        self._ready = True
        self.readyChanged.emit(True)

    def _connect_signals(self) -> None:
        if self._signals_connected:
            return
        assert self._session
        ok_pressed = self.bus.connect(
            PORTAL_SERVICE,
            PORTAL_PATH,
            INTERFACE,
            "Activated",
            _SHORTCUT_SIGNAL_SIGNATURE,
            self,
            _ACTIVATED_SLOT,
        )
        ok_released = self.bus.connect(
            PORTAL_SERVICE,
            PORTAL_PATH,
            INTERFACE,
            "Deactivated",
            _SHORTCUT_SIGNAL_SIGNATURE,
            self,
            _DEACTIVATED_SLOT,
        )
        if not (ok_pressed and ok_released):
            if ok_pressed:
                self.bus.disconnect(
                    PORTAL_SERVICE,
                    PORTAL_PATH,
                    INTERFACE,
                    "Activated",
                    _SHORTCUT_SIGNAL_SIGNATURE,
                    self,
                    _ACTIVATED_SLOT,
                )
            if ok_released:
                self.bus.disconnect(
                    PORTAL_SERVICE,
                    PORTAL_PATH,
                    INTERFACE,
                    "Deactivated",
                    _SHORTCUT_SIGNAL_SIGNATURE,
                    self,
                    _DEACTIVATED_SLOT,
                )
            raise RuntimeError("Impossibile ascoltare i segnali GlobalShortcuts")
        self._signals_connected = True

    @Slot(QDBusObjectPath, str, "qulonglong", "QVariantMap")
    def _activated(
        self,
        session: QDBusObjectPath,
        shortcut_id: str,
        _timestamp: int,
        _options: dict,
    ) -> None:
        if shortcut_id == SHORTCUT_ID and object_path(session) == self._session:
            self.pressed.emit()

    @Slot(QDBusObjectPath, str, "qulonglong", "QVariantMap")
    def _deactivated(
        self,
        session: QDBusObjectPath,
        shortcut_id: str,
        _timestamp: int,
        _options: dict,
    ) -> None:
        if shortcut_id == SHORTCUT_ID and object_path(session) == self._session:
            self.released.emit()

    def close(self) -> None:
        self._reset()

    def _reset(self) -> None:
        """Release every resource that may exist after a partial portal startup."""
        self.close_requests()
        if self._signals_connected:
            self.bus.disconnect(
                PORTAL_SERVICE,
                PORTAL_PATH,
                INTERFACE,
                "Activated",
                _SHORTCUT_SIGNAL_SIGNATURE,
                self,
                _ACTIVATED_SLOT,
            )
            self.bus.disconnect(
                PORTAL_SERVICE,
                PORTAL_PATH,
                INTERFACE,
                "Deactivated",
                _SHORTCUT_SIGNAL_SIGNATURE,
                self,
                _DEACTIVATED_SLOT,
            )
            self._signals_connected = False
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
