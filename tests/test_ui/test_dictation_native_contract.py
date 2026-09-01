from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_native_dictation_does_not_use_xdotool_or_pynput():
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "ui" / "native").glob("*.py"))
    assert "xdotool" not in source
    assert "pynput" not in source


def test_overlay_is_local_webengine_without_second_webchannel_and_cannot_focus():
    source = (ROOT / "ui" / "native" / "dictation_overlay.py").read_text(encoding="utf-8")
    html = (ROOT / "ui" / "web" / "dictation_overlay.html").read_text(encoding="utf-8")
    css = (ROOT / "ui" / "web" / "dictation_overlay.css").read_text(encoding="utf-8")
    assert "QWebEngineView" in source
    assert "LocalOnlyWebPage" in source
    assert "QtWebChannel" not in source
    assert "registerObject(" not in source
    assert "WindowDoesNotAcceptFocus" in source
    assert "WA_ShowWithoutActivating" in source
    assert "dictation_overlay.css" in html
    assert "rgb(20, 20, 20)" in css
    assert "rgb(255, 102, 0)" in css


def test_remote_desktop_requests_keyboard_only_with_typed_dbus_variants():
    source = (ROOT / "ui" / "native" / "remote_desktop.py").read_text(encoding="utf-8")
    assert "KEYBOARD = 1" in source
    assert '"types": uint_variant(KEYBOARD)' in source
    assert '"persist_mode": uint_variant(2)' in source
    assert '"oa{sv}iu"' in source
    assert "NotifyKeyboardKeysym" in source


def test_remote_desktop_persists_permission_restore_token():
    source = (ROOT / "ui" / "native" / "remote_desktop.py").read_text(encoding="utf-8")
    assert 'string_variant(self._restore_token)' in source
    assert "restoreTokenChanged" in source


def test_clipboard_restore_is_guarded_by_transaction_marker():
    source = (ROOT / "ui" / "native" / "text_injector.py").read_text(encoding="utf-8")
    assert "_MARKER_MIME" in source
    assert "_restore_if_owned" in source
    assert "pasteCompleted" in source
    assert "_active_transaction" in source


def test_portal_transport_is_typed_and_runs_off_the_gui_thread():
    source = (ROOT / "ui" / "native" / "xdg_portal.py").read_text(encoding="utf-8")
    assert "from dbus_next" in source
    assert "from dbus_next.aio import MessageBus" in source
    assert "threading.Thread(" in source
    assert 'name="DictationPortalDBus"' in source
    assert "MessageBus(bus_type=BusType.SESSION)" in source
    assert "QDBusInterface" not in source
    assert "QDBusConnection" not in source
    assert "PyObjectWrapper" not in source


def test_global_shortcuts_uses_exact_typed_bind_signature():
    source = (ROOT / "ui" / "native" / "global_shortcuts.py").read_text(encoding="utf-8")
    assert '"oa(sa{sv})sa{sv}"' in source
    assert '"description": string_variant(' in source
    assert "subscribe_signal(" in source
    assert "QDBus" not in source


def test_native_integration_owns_one_shared_portal_transport():
    source = (ROOT / "ui" / "native" / "dictation_integration.py").read_text(encoding="utf-8")
    assert "self._portal_transport = PortalTransport(self)" in source
    assert "GlobalShortcutsPortal(self._portal_transport, self)" in source
    assert "self._portal_transport," in source
    assert "self._portal_transport.close()" in source


def test_native_integration_prepares_remote_desktop_before_first_hotkey():
    source = (ROOT / "ui" / "native" / "dictation_integration.py").read_text(encoding="utf-8")
    start = source.index("def start(self)")
    remote = source.index("self._remote.ensure_ready()", start)
    shortcut = source.index("self._shortcut.start()", start)
    assert remote < shortcut
