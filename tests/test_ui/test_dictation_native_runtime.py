from PySide6.QtCore import QMimeData, QObject, Signal

import ui.native.text_injector as injector_module
from ui.native.global_shortcuts import GlobalShortcutsPortal
from ui.native.text_injector import SystemTextInjector


class _FakeRemote(QObject):
    readyChanged = Signal(bool)
    errorOccurred = Signal(str)

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
    assert len(_FakeTimer.callbacks) == 1

    injector.begin_session()
    injector.insert_final("new")
    assert remote.paste_calls == 1

    _FakeTimer.callbacks.pop(0)()
    assert completed == []
    assert remote.paste_calls == 2

    _FakeTimer.callbacks.pop(0)()
    assert completed == ["new"]
    assert clipboard.mimeData().text() == "before"


def test_global_shortcuts_reset_releases_partial_session(monkeypatch):
    portal = GlobalShortcutsPortal()
    disconnects = []
    closed_sessions = []

    class FakeBus:
        def disconnect(self, *args):
            disconnects.append(args)
            return True

    portal.bus = FakeBus()
    portal._signals_connected = True
    portal._session = "/org/freedesktop/portal/desktop/session/test"
    portal._ready = True
    portal._starting = True
    monkeypatch.setattr(portal, "close_requests", lambda: None)
    monkeypatch.setattr(portal, "close_session", closed_sessions.append)

    ready = []
    portal.readyChanged.connect(ready.append)
    portal._reset()

    assert len(disconnects) == 2
    assert closed_sessions == ["/org/freedesktop/portal/desktop/session/test"]
    assert ready == [False]
    assert portal._session is None
    assert portal._signals_connected is False
    assert portal._starting is False
