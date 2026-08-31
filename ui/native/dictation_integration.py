"""Native composition for global shortcut, overlay and system text injection."""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from core.application_service import ApplicationService
from core.dictation_portal_state import DictationPortalStateStore
from ui.native.dictation_overlay import DictationOverlay
from ui.native.global_shortcuts import GlobalShortcutsPortal
from ui.native.remote_desktop import RemoteDesktopKeyboardPortal
from ui.native.text_injector import SystemTextInjector

logger = logging.getLogger(__name__)


class DictationNativeIntegration(QObject):
    """Bridge application dictation events to desktop-native capabilities only."""

    _eventArrived = Signal(str, object)
    _EVENTS = (
        "dictation_activation_changed",
        "dictation_session_changed",
        "dictation_preview_changed",
        "dictation_text_committed",
        "dictation_final_text",
        "dictation_error",
    )

    def __init__(
        self,
        application: ApplicationService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._application = application
        self._portal_state = DictationPortalStateStore()
        self._shortcut = GlobalShortcutsPortal(self)
        self._remote = RemoteDesktopKeyboardPortal(
            self._portal_state.restore_token(),
            self,
        )
        self._injector = SystemTextInjector(self._remote, self)
        self._overlay = DictationOverlay()
        self._subscriptions: list[tuple[str, object]] = []
        self._closed = False
        self._session_status = "idle"
        self._session_insertion_mode = application.dictation_insertion_mode()
        self._eventArrived.connect(self._handle_event)
        self._shortcut.pressed.connect(self._application.dictation_shortcut_pressed)
        self._shortcut.released.connect(self._application.dictation_shortcut_released)
        self._shortcut.errorOccurred.connect(self._native_error)
        self._injector.errorOccurred.connect(self._native_error)
        self._injector.insertionCompleted.connect(self._application.dictation_text_inserted)
        self._remote.restoreTokenChanged.connect(self._persist_restore_token)
        for event in self._EVENTS:
            handler = self._make_handler(event)
            application.subscribe(event, handler)
            self._subscriptions.append((event, handler))

    def start(self) -> None:
        # Ask for RemoteDesktop while UltraTranscribr owns focus. Waiting until
        # the first hotkey press could make the permission dialog steal focus
        # from the external field that should receive the first dictation.
        self._remote.ensure_ready()
        self._shortcut.start()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for event, handler in self._subscriptions:
            self._application.unsubscribe(event, handler)
        self._subscriptions.clear()
        self._injector.close()
        self._remote.close()
        self._shortcut.close()
        self._overlay.hide()
        self._overlay.deleteLater()

    def _make_handler(self, event: str):
        def handler(payload: Any) -> None:
            self._eventArrived.emit(event, payload)

        return handler

    @Slot(str, object)
    def _handle_event(self, event: str, payload: Any) -> None:
        if event == "dictation_activation_changed":
            if bool((payload or {}).get("active")):
                self._remote.ensure_ready()
            return
        if event == "dictation_session_changed":
            status = str((payload or {}).get("status") or "idle")
            self._session_status = status
            if status == "starting":
                self._session_insertion_mode = self._application.dictation_insertion_mode()
                self._injector.begin_session()
            self._overlay.update_state(status)
            return
        if event == "dictation_preview_changed":
            self._overlay.update_state(
                self._session_status,
                str((payload or {}).get("pending") or ""),
            )
            return
        if event == "dictation_text_committed":
            if self._session_insertion_mode == "live":
                self._injector.insert_delta(str(payload or ""))
            return
        if event == "dictation_final_text":
            if self._session_insertion_mode == "final":
                self._injector.insert_final(str(payload or ""))
            return
        if event == "dictation_error":
            self._session_status = "error"
            self._overlay.update_state("error", str(payload or ""))

    @Slot(str)
    def _persist_restore_token(self, token: str) -> None:
        try:
            self._portal_state.set_restore_token(str(token or "") or None)
        except Exception:
            logger.exception("Persistenza restore token RemoteDesktop fallita")

    @Slot(str)
    def _native_error(self, message: str) -> None:
        logger.error("Integrazione nativa dettatura: %s", message)
        self._session_status = "error"
        self._overlay.update_state("error", message)
