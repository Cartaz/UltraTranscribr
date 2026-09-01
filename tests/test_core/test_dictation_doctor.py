from tools import dictation_doctor
from tools.dictation_doctor import Check, exit_code


def test_doctor_exit_code_fails_only_on_fail():
    assert exit_code([Check("a", "ok", ""), Check("b", "warn", "")]) == 0
    assert exit_code([Check("a", "fail", "")]) == 1


def test_doctor_accepts_portal_that_is_only_dbus_activatable(monkeypatch):
    monkeypatch.setattr(dictation_doctor, "_module_available", lambda _name: True)
    monkeypatch.setattr(dictation_doctor.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, timeout=5.0):
        del timeout
        if "introspect" in command:
            return 0, "\n".join((
                "org.freedesktop.portal.GlobalShortcuts",
                "org.freedesktop.portal.RemoteDesktop",
                "NotifyKeyboardKeysym",
                "AvailableDeviceTypes",
            ))
        if "--activatable" in command:
            return 0, "org.freedesktop.portal.Desktop"
        return 0, ":1.42"

    monkeypatch.setattr(dictation_doctor, "run", fake_run)
    checks = dictation_doctor.collect({
        "XDG_SESSION_TYPE": "wayland",
        "XDG_CURRENT_DESKTOP": "KDE",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/bus",
    })

    by_name = {item.name: item for item in checks}
    assert by_name["portal-service"] == Check("portal-service", "ok", "attivabile")
    assert by_name["dbus-next"].status == "ok"
    assert exit_code(checks) == 0


def test_doctor_does_not_warn_when_portal_binaries_are_outside_path(monkeypatch):
    monkeypatch.setattr(dictation_doctor, "_module_available", lambda _name: True)

    def fake_which(name):
        if name == "busctl":
            return "/usr/bin/busctl"
        return None

    monkeypatch.setattr(dictation_doctor.shutil, "which", fake_which)

    def fake_run(command, timeout=5.0):
        del timeout
        if "introspect" in command:
            return 0, "\n".join((
                "org.freedesktop.portal.GlobalShortcuts",
                "org.freedesktop.portal.RemoteDesktop",
                "NotifyKeyboardKeysym",
                "AvailableDeviceTypes",
            ))
        if "--activatable" in command:
            return 0, "org.freedesktop.portal.Desktop"
        return 0, "org.freedesktop.portal.Desktop"

    monkeypatch.setattr(dictation_doctor, "run", fake_run)
    checks = dictation_doctor.collect({
        "XDG_SESSION_TYPE": "wayland",
        "XDG_CURRENT_DESKTOP": "KDE",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/bus",
    })
    by_name = {item.name: item for item in checks}
    assert by_name["xdg-desktop-portal"].status == "ok"
    assert by_name["xdg-desktop-portal-kde"].status == "ok"
    assert "non nel PATH" in by_name["xdg-desktop-portal"].detail
    assert exit_code(checks) == 0


def test_doctor_fails_when_dbus_next_is_missing(monkeypatch):
    monkeypatch.setattr(
        dictation_doctor,
        "_module_available",
        lambda name: name != "dbus_next",
    )
    monkeypatch.setattr(dictation_doctor.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, timeout=5.0):
        del timeout
        if "introspect" in command:
            return 0, "\n".join((
                "org.freedesktop.portal.GlobalShortcuts",
                "org.freedesktop.portal.RemoteDesktop",
                "NotifyKeyboardKeysym",
                "AvailableDeviceTypes",
            ))
        return 0, "org.freedesktop.portal.Desktop"

    monkeypatch.setattr(dictation_doctor, "run", fake_run)
    checks = dictation_doctor.collect({
        "XDG_SESSION_TYPE": "wayland",
        "XDG_CURRENT_DESKTOP": "KDE",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/bus",
    })
    by_name = {item.name: item for item in checks}
    assert by_name["dbus-next"].status == "fail"
    assert exit_code(checks) == 1


def test_doctor_fails_when_portal_cannot_be_introspected(monkeypatch):
    monkeypatch.setattr(dictation_doctor, "_module_available", lambda _name: True)
    monkeypatch.setattr(dictation_doctor.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, timeout=5.0):
        del timeout
        if "introspect" in command:
            return 1, "portal unavailable"
        return 0, ""

    monkeypatch.setattr(dictation_doctor, "run", fake_run)
    checks = dictation_doctor.collect({
        "XDG_SESSION_TYPE": "wayland",
        "XDG_CURRENT_DESKTOP": "KDE",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/bus",
    })

    by_name = {item.name: item for item in checks}
    assert by_name["portal-service"].status == "fail"
    assert by_name["portal-introspection"].detail == "portal unavailable"
    assert exit_code(checks) == 1
