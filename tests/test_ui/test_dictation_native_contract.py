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


def test_remote_desktop_requests_keyboard_only():
    source = (ROOT / "ui" / "native" / "remote_desktop.py").read_text(encoding="utf-8")
    assert "KEYBOARD = 1" in source
    assert '"types": KEYBOARD' in source
    assert "NotifyKeyboardKeysym" in source


def test_remote_desktop_persists_permission_restore_token():
    source = (ROOT / "ui" / "native" / "remote_desktop.py").read_text(encoding="utf-8")
    assert '"persist_mode": 2' in source
    assert '"restore_token"' in source
    assert "restoreTokenChanged" in source


def test_clipboard_restore_is_guarded_by_transaction_marker():
    source = (ROOT / "ui" / "native" / "text_injector.py").read_text(encoding="utf-8")
    assert "_MARKER_MIME" in source
    assert "_restore_if_owned" in source


def test_portal_request_uses_exact_dbus_signature_and_pre_subscribes():
    source = (ROOT / "ui" / "native" / "xdg_portal.py").read_text(encoding="utf-8")
    assert '_RESPONSE_DBUS_SIGNATURE = "ua{sv}"' in source
    assert 'SLOT("_response(uint,QVariantMap)")' in source
    assert '@Slot("uint", "QVariantMap")' in source
    assert "baseService()" in source
    assert "predicted_request_path" in source
    request_position = source.index("request_ref = PortalRequest")
    call_position = source.index("message = interface.call", request_position)
    assert request_position < call_position


def test_global_shortcuts_uses_exact_signal_signature():
    source = (ROOT / "ui" / "native" / "global_shortcuts.py").read_text(encoding="utf-8")
    assert '_SHORTCUT_SIGNAL_SIGNATURE = "osta{sv}"' in source
    assert "qulonglong" in source
    assert "QVariantMap" in source
    assert 'SLOT("_activated(QDBusObjectPath,QString,qulonglong,QVariantMap)")' in source
    assert 'SLOT("_deactivated(QDBusObjectPath,QString,qulonglong,QVariantMap)")' in source


def test_remote_desktop_rejects_unexpected_device_grants_and_checks_call_reply():
    source = (ROOT / "ui" / "native" / "remote_desktop.py").read_text(encoding="utf-8")
    assert "devices != KEYBOARD" in source
    assert "QDBusInterface(" in source
    assert 'reply = interface.call(' in source
    assert "MessageType.ErrorMessage" in source


def test_native_integration_prepares_remote_desktop_before_first_hotkey():
    source = (ROOT / "ui" / "native" / "dictation_integration.py").read_text(encoding="utf-8")
    start = source.index("def start(self)")
    remote = source.index("self._remote.ensure_ready()", start)
    shortcut = source.index("self._shortcut.start()", start)
    assert remote < shortcut
