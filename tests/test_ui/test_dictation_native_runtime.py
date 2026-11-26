from PySide6.QtCore import QMimeData, QObject, Signal

import ui.native.text_injector as injector_module
from ui.native.global_shortcuts import GlobalShortcutsPortal
from ui.native.text_injector import QtClipboardSwap, SystemTextInjector


class _FakeRemote(QObject):
    readyChanged = Signal(bool)
    errorOccurred = Signal(str)
    pasteCompleted = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.ready = True
        self.paste_calls = 0
        self.in_flight = False

    def ensure_ready(self) -> None:
        pass

    def paste_shortcut(self) -> bool:
        if self.in_flight:
            return False
        self.paste_calls += 1
        self.in_flight = True
        return True

    def complete(self) -> None:
        self.in_flight = False
        self.pasteCompleted.emit()

    def cancel_paste(self) -> None:
        self.in_flight = False


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
    timeouts = []

    @classmethod
    def singleShot(cls, delay, callback):
        if delay == injector_module._CLIPBOARD_SETTLE_MS:
            callback()  # clipboard settling is not under test here
        elif delay in (injector_module._PASTE_TIMEOUT_MS, injector_module._MAX_HOLD_MS):
            cls.timeouts.append(callback)
        else:
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
    _FakeTimer.timeouts = []
    monkeypatch.setattr(
        injector_module,
        "QGuiApplication",
        type("FakeGuiApplication", (), {"clipboard": staticmethod(lambda: clipboard)}),
    )
    monkeypatch.setattr(injector_module, "QTimer", _FakeTimer)

    remote = _FakeRemote()
    injector = SystemTextInjector(remote, clipboard=QtClipboardSwap())
    completed = []
    injector.insertionCompleted.connect(completed.append)

    injector.begin_session()
    injector.insert_final("old")
    assert remote.paste_calls == 1
    assert len(_FakeTimer.callbacks) == 0

    injector.begin_session()
    injector.insert_final("new")
    assert remote.paste_calls == 1

    remote.complete()
    assert len(_FakeTimer.callbacks) == 1
    _FakeTimer.callbacks.pop(0)()
    assert completed == []
    assert remote.paste_calls == 2

    remote.complete()
    assert len(_FakeTimer.callbacks) == 1
    _FakeTimer.callbacks.pop(0)()
    assert completed == ["new"]
    assert clipboard.mimeData().text() == "before"


def test_remote_error_restores_clipboard_transaction(monkeypatch):
    clipboard = _FakeClipboard()
    _FakeTimer.callbacks = []
    _FakeTimer.timeouts = []
    monkeypatch.setattr(
        injector_module,
        "QGuiApplication",
        type("FakeGuiApplication", (), {"clipboard": staticmethod(lambda: clipboard)}),
    )
    monkeypatch.setattr(injector_module, "QTimer", _FakeTimer)

    remote = _FakeRemote()
    injector = SystemTextInjector(remote, clipboard=QtClipboardSwap())
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


class _FakeSwap:
    def __init__(self) -> None:
        self.contents = "before"

    def swap_in(self, text):
        token = (text, self.contents)
        self.contents = text
        return token

    def restore(self, token):
        text, previous = token
        if self.contents == text:
            self.contents = previous


def test_insertion_waits_until_the_shortcut_keys_are_released(monkeypatch):
    _FakeTimer.callbacks = []
    _FakeTimer.timeouts = []
    monkeypatch.setattr(injector_module, "QTimer", _FakeTimer)
    remote = _FakeRemote()
    injector = SystemTextInjector(remote, clipboard=_FakeSwap())
    injector.begin_session()
    injector.set_shortcut_held(True)
    injector.insert_delta("ciao")
    # Shift+Insert while Meta is held would reach the app as Meta+Shift+Insert.
    assert remote.paste_calls == 0
    injector.set_shortcut_held(False)
    assert remote.paste_calls == 0
    _FakeTimer.callbacks.pop(0)()  # modifiers settled
    assert remote.paste_calls == 1


def test_unconfirmed_paste_times_out_and_unblocks_the_queue(monkeypatch):
    _FakeTimer.callbacks = []
    _FakeTimer.timeouts = []
    monkeypatch.setattr(injector_module, "QTimer", _FakeTimer)
    remote = _FakeRemote()
    swap = _FakeSwap()
    injector = SystemTextInjector(remote, clipboard=swap)
    errors = []
    injector.errorOccurred.connect(errors.append)
    injector.begin_session()
    injector.insert_delta("uno")
    assert remote.paste_calls == 1 and swap.contents == "uno"
    _FakeTimer.timeouts.pop(0)()
    assert errors == ["Incolla non confermato da RemoteDesktop"]
    # The old key sequence may still land: sending "due" now could paste it
    # twice, so it waits for the portal to report back.
    injector.insert_delta("due")
    assert remote.paste_calls == 1
    remote.complete()
    _FakeTimer.callbacks.pop(0)()
    assert remote.paste_calls == 2


def test_new_session_is_not_blocked_by_a_paste_the_portal_never_confirmed(monkeypatch):
    _FakeTimer.callbacks = []
    _FakeTimer.timeouts = []
    monkeypatch.setattr(injector_module, "QTimer", _FakeTimer)
    remote = _FakeRemote()
    injector = SystemTextInjector(remote, clipboard=_FakeSwap())
    injector.begin_session()
    injector.insert_final("persa")
    _FakeTimer.timeouts.pop(0)()
    injector.begin_session()
    injector.insert_final("nuova")
    assert remote.paste_calls == 2


def test_text_arriving_right_after_release_still_waits_for_modifiers(monkeypatch):
    _FakeTimer.callbacks = []
    _FakeTimer.timeouts = []
    monkeypatch.setattr(injector_module, "QTimer", _FakeTimer)
    remote = _FakeRemote()
    injector = SystemTextInjector(remote, clipboard=_FakeSwap())
    injector.begin_session()
    injector.set_shortcut_held(True)
    injector.set_shortcut_held(False)
    injector.insert_final("finale")
    assert remote.paste_calls == 0
    _FakeTimer.callbacks.pop(0)()
    assert remote.paste_calls == 1


def test_paste_confirmed_just_before_the_timeout_is_not_reported_as_failed(monkeypatch):
    _FakeTimer.callbacks = []
    _FakeTimer.timeouts = []
    monkeypatch.setattr(injector_module, "QTimer", _FakeTimer)
    remote = _FakeRemote()
    injector = SystemTextInjector(remote, clipboard=_FakeSwap())
    errors, completed = [], []
    injector.errorOccurred.connect(errors.append)
    injector.insertionCompleted.connect(completed.append)
    injector.begin_session()
    injector.insert_final("ok")
    remote.complete()
    _FakeTimer.timeouts.pop(0)()  # fires before the delayed restore
    _FakeTimer.callbacks.pop(0)()
    assert errors == [] and completed == ["ok"]
