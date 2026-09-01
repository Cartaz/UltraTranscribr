#!/usr/bin/env python3
"""Read-only environment checks for UltraTranscribr global dictation."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def run(command: Sequence[str], timeout: float = 5.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return proc.returncode, proc.stdout.strip()


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _portal_registration_state(service: str, active: str, activatable: str) -> str:
    if service in active:
        return "attivo"
    if service in activatable:
        return "attivabile"
    return "non elencato"


def collect(env: Mapping[str, str] | None = None) -> list[Check]:
    environment = os.environ if env is None else env
    checks: list[Check] = []

    session_type = str(environment.get("XDG_SESSION_TYPE", "")).lower()
    checks.append(Check(
        "session-wayland",
        "ok" if session_type == "wayland" else "fail",
        session_type or "non rilevata",
    ))
    desktop = str(environment.get("XDG_CURRENT_DESKTOP", ""))
    checks.append(Check(
        "desktop-kde",
        "ok" if "kde" in desktop.lower() else "warn",
        desktop or "non rilevato",
    ))
    session_bus = str(environment.get("DBUS_SESSION_BUS_ADDRESS", ""))
    checks.append(Check(
        "session-dbus",
        "ok" if session_bus else "fail",
        "configurato" if session_bus else "DBUS_SESSION_BUS_ADDRESS assente",
    ))
    dbus_next_available = _module_available("dbus_next")
    checks.append(Check(
        "dbus-next",
        "ok" if dbus_next_available else "fail",
        "dbus-next importabile" if dbus_next_available else "dbus-next non disponibile",
    ))

    busctl = shutil.which("busctl")
    if not busctl:
        checks.append(Check("busctl", "fail", "busctl non trovato"))
        return checks
    checks.append(Check("busctl", "ok", busctl))

    code, listing = run([busctl, "--user", "--no-pager", "--list"])
    if code != 0:
        checks.append(Check("portal-service", "fail", listing or "bus di sessione non interrogabile"))
        return checks

    code, activatable = run([
        busctl,
        "--user",
        "--no-pager",
        "--activatable",
        "--list",
    ])
    if code != 0:
        activatable = ""

    service = "org.freedesktop.portal.Desktop"
    registration = _portal_registration_state(service, listing, activatable)
    code, introspection = run([
        busctl,
        "--user",
        "--no-pager",
        "introspect",
        service,
        "/org/freedesktop/portal/desktop",
    ])
    if code != 0:
        checks.append(Check("portal-service", "fail", registration))
        checks.append(Check("portal-introspection", "fail", introspection or "introspection fallita"))
        return checks
    checks.append(Check("portal-service", "ok", registration))
    checks.append(Check("portal-introspection", "ok", "interfacce portal interrogabili"))
    checks.append(Check(
        "global-shortcuts",
        "ok" if "org.freedesktop.portal.GlobalShortcuts" in introspection else "fail",
        "interfaccia GlobalShortcuts",
    ))
    checks.append(Check(
        "remote-desktop",
        "ok" if "org.freedesktop.portal.RemoteDesktop" in introspection else "fail",
        "interfaccia RemoteDesktop",
    ))
    checks.append(Check(
        "notify-keysym",
        "ok" if "NotifyKeyboardKeysym" in introspection else "fail",
        "metodo NotifyKeyboardKeysym",
    ))
    checks.append(Check(
        "available-device-types",
        "ok" if "AvailableDeviceTypes" in introspection else "warn",
        "proprietà device types",
    ))

    for binary in ("xdg-desktop-portal", "xdg-desktop-portal-kde"):
        path = shutil.which(binary)
        checks.append(Check(
            binary,
            "ok",
            path or "servizio D-Bus operativo; eseguibile non nel PATH",
        ))
    return checks


def exit_code(checks: Sequence[Check]) -> int:
    return 1 if any(item.status == "fail" for item in checks) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="stampa JSON")
    args = parser.parse_args()
    checks = collect()
    if args.json:
        print(json.dumps([asdict(item) for item in checks], indent=2, ensure_ascii=False))
    else:
        for item in checks:
            print(f"[{item.status.upper():4}] {item.name}: {item.detail}")
    return exit_code(checks)


if __name__ == "__main__":
    raise SystemExit(main())
