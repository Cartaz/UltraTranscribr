from PySide6.QtCore import QMimeData, QObject, Signal

import ui.native.text_injector as injector_module
from ui.native.global_shortcuts import GlobalShortcutsPortal
from ui.native.text_injector import SystemTextInjector


class _FakeRemote(QObject):
    readyChanged = Signal(bool)
    errorOccurred = Signal(str)
    pasteCompleted = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.ready = True
        self.paste_calls = 0

    def ensure_ready(self) -> None:
        pass

    def paste_shortcut(self) -> bool:
        self.paste_calls += 1
        return True


class _FakeClipboard:
    def __init__(self) -> None:
        self._mime = QMimeData()
        self._mime.setText("before")

    def mimeData(self):
        return self._mime

    def setMimeData(self, mime):
        self._mime = mime


class _FakeTimer:
    callbacks = []

    @classmethod
    def singleShot(cls, _delay, callback):
        cls.callbacks.append(callback)


class _FakePortalTransport:
    def __init__(self) -> None:
        self.subscriptions = []
        self.unsubscriptions = []
        self.closed_sessions = []
        self.cancelled_requests = []

    def subscribe_portal_signal(self, interface_name, member, callback):
        key = f"sub-{len(self.subscriptions) + 1}"
        self.subscriptions.append((key, interface_name, member, callback))
        return key

    def unsubscribe_portal_signal(self, subscription_id):
        self.unsubscriptions.append(subscription_id)

    def close_session(self, session):
        self.closed_sessions.append(session)

    def cancel_request(self, request_id):
        self.cancelled_requests.append(request_id)

    def close(self):
        pass


def test_stale_insertion_completion_does_not_leak_into_next_session(monkeypatch):
    clipboard = _FakeClipboard()
    _FakeTimer.callbacks = []
    monkeypatch.setattr(
        injector_module,
        "QGuiApplication",
        type("FakeGuiApplication", (), {"clipboard": staticmethod(lambda: clipboard)}),
    )
    monkeypatch.setattr(injector_module, "QTimer", _FakeTimer)

    remote = _FakeRemote()
    injector = SystemTextInjector(remote)
    completed = []
    injector.insertionCompleted.connect(completed.append)

    injector.begin_session()
    injector.insert_final("old")
    assert remote.paste_calls == 1
    assert len(_FakeTimer.callbacks) == 0

    injector.begin_session()
    injector.insert_final("new")
    assert remote.paste_calls == 1

    remote.pasteCompleted.emit()
    assert len(_FakeTimer.callbacks) == 1
    _FakeTimer.callbacks.pop(0)()
    assert completed == []
    assert remote.paste_calls == 2

    remote.pasteCompleted.emit()
    assert len(_FakeTimer.callbacks) == 1
    _FakeTimer.callbacks.pop(0)()
    assert completed == ["new"]
    assert clipboard.mimeData().text() == "before"


def test_remote_error_restores_clipboard_transaction(monkeypatch):
    clipboard = _FakeClipboard()
    _FakeTimer.callbacks = []
    monkeypatch.setattr(
        injector_module,
        "QGuiApplication",
        type("FakeGuiApplication", (), {"clipboard": staticmethod(lambda: clipboard)}),
    )
    monkeypatch.setattr(injector_module, "QTimer", _FakeTimer)

    remote = _FakeRemote()
    injector = SystemTextInjector(remote)
    errors = []
    injector.errorOccurred.connect(errors.append)
    injector.begin_session()
    injector.insert_final("temporary")
    assert clipboard.mimeData().text() == "temporary"

    remote.errorOccurred.emit("portal failed")
    assert clipboard.mimeData().text() == "before"
    assert errors == ["portal failed"]


def test_global_shortcuts_reset_releases_partial_session():
    transport = _FakePortalTransport()
    portal = GlobalShortcutsPortal(transport=transport)
    portal._activated_subscription = portal.subscribe_signal("iface", "Activated", lambda _body: None)
    portal._deactivated_subscription = portal.subscribe_signal("iface", "Deactivated", lambda _body: None)
    portal._session = "/org/freedesktop/portal/desktop/session/test"
    portal._ready = True
    portal._starting = True

    ready = []
    portal.readyChanged.connect(ready.append)
    portal._reset()

    assert len(transport.unsubscriptions) == 2
    assert transport.closed_sessions == ["/org/freedesktop/portal/desktop/session/test"]
    assert ready == [False]
    assert portal._session is None
    assert portal._activated_subscription is None
    assert portal._deactivated_subscription is None
    assert portal._starting is False
