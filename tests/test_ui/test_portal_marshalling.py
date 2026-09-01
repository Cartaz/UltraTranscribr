from dbus_next import Variant

from ui.native.global_shortcuts import GlobalShortcutsPortal
from ui.native.remote_desktop import KEYBOARD, RemoteDesktopKeyboardPortal
from ui.native.xdg_portal import predicted_request_path, uint_variant


class _FakeTransport:
    def __init__(self) -> None:
        self.requests = []
        self.sequences = []
        self.subscriptions = []
        self.closed_sessions = []
        self.cancelled = []

    def call_request(
        self,
        interface_name,
        method,
        signature,
        body,
        *,
        handle_token,
        callback,
        error_callback,
    ):
        self.requests.append({
            "interface": interface_name,
            "method": method,
            "signature": signature,
            "body": body,
            "handle_token": handle_token,
            "callback": callback,
            "error_callback": error_callback,
        })
        return f"request-{len(self.requests)}"

    def cancel_request(self, request_id):
        self.cancelled.append(request_id)

    def call_sequence(self, interface_name, calls, callback):
        self.sequences.append((interface_name, calls, callback))
        return f"sequence-{len(self.sequences)}"

    def close_session(self, path):
        self.closed_sessions.append(path)

    def subscribe_portal_signal(self, interface_name, member, callback):
        value = f"subscription-{len(self.subscriptions) + 1}"
        self.subscriptions.append((value, interface_name, member, callback))
        return value

    def unsubscribe_portal_signal(self, _subscription_id):
        pass

    def close(self):
        pass


def test_uint_variant_preserves_dbus_uint32_type():
    value = uint_variant(KEYBOARD)
    assert isinstance(value, Variant)
    assert value.signature == "u"
    assert value.value == KEYBOARD


def test_remote_desktop_select_devices_uses_uint32_options():
    transport = _FakeTransport()
    portal = RemoteDesktopKeyboardPortal(transport=transport)
    portal._created(0, {"session_handle": "/org/freedesktop/portal/desktop/session/test"})

    request = transport.requests[-1]
    assert request["method"] == "SelectDevices"
    assert request["signature"] == "oa{sv}"
    options = request["body"][1]
    assert options["types"].signature == "u"
    assert options["types"].value == KEYBOARD
    assert options["persist_mode"].signature == "u"
    assert options["persist_mode"].value == 2


def test_global_shortcuts_bind_uses_typed_array_of_structs():
    transport = _FakeTransport()
    portal = GlobalShortcutsPortal(transport=transport)
    portal._created(0, {"session_handle": "/org/freedesktop/portal/desktop/session/test"})

    request = transport.requests[-1]
    assert request["method"] == "BindShortcuts"
    assert request["signature"] == "oa(sa{sv})sa{sv}"
    shortcut = request["body"][1][0]
    assert shortcut[0] == "dictation"
    assert shortcut[1]["description"].signature == "s"
    assert len(transport.subscriptions) == 2


def test_remote_desktop_paste_sequence_uses_keysym_int32_and_state_uint32():
    transport = _FakeTransport()
    portal = RemoteDesktopKeyboardPortal(transport=transport)
    portal._session = "/org/freedesktop/portal/desktop/session/test"
    portal._ready = True

    assert portal.paste_shortcut() is True
    interface_name, calls, callback = transport.sequences[-1]
    assert interface_name == "org.freedesktop.portal.RemoteDesktop"
    assert len(calls) == 4
    assert all(signature == "oa{sv}iu" for _member, signature, _body in calls)
    assert all(member == "NotifyKeyboardKeysym" for member, _signature, _body in calls)

    completed = []
    portal.pasteCompleted.connect(lambda: completed.append(True))
    callback(None)
    assert completed == [True]


def test_predicted_request_path_matches_portal_naming_rule():
    assert predicted_request_path(":1.42", "request_token") == (
        "/org/freedesktop/portal/desktop/request/1_42/request_token"
    )
