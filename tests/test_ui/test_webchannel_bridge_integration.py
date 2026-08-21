"""Headless integration coverage for the Qt WebChannel presentation boundary."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from config.settings import Settings


ROOT = Path(__file__).resolve().parents[2]


class _BoundSignal:
    def __init__(self) -> None:
        self.handlers = []

    def connect(self, handler) -> None:
        self.handlers.append(handler)

    def emit(self, *args) -> None:
        for handler in list(self.handlers):
            handler(*args)


class _SignalDescriptor:
    def __init__(self, *types) -> None:
        del types
        self._name = ""

    def __set_name__(self, owner, name) -> None:
        del owner
        self._name = f"__signal_{name}"

    def __get__(self, obj, owner):
        if obj is None:
            return self
        signal = obj.__dict__.get(self._name)
        if signal is None:
            signal = _BoundSignal()
            obj.__dict__[self._name] = signal
        return signal


def _slot(*types, **kwargs):
    del types, kwargs

    def decorate(fn):
        return fn

    return decorate


class _QObject:
    def __init__(self, parent=None) -> None:
        self.parent = parent


class _QFileDialog:
    @staticmethod
    def getOpenFileName(*args, **kwargs):
        del args, kwargs
        return "", ""

    @staticmethod
    def getSaveFileName(*args, **kwargs):
        del args, kwargs
        return "", ""


def _load_bridges(monkeypatch):
    pyside = ModuleType("PySide6")
    qtcore = ModuleType("PySide6.QtCore")
    qtcore.QObject = _QObject
    qtcore.Signal = _SignalDescriptor
    qtcore.Slot = _slot
    qtwidgets = ModuleType("PySide6.QtWidgets")
    qtwidgets.QFileDialog = _QFileDialog
    monkeypatch.setitem(sys.modules, "PySide6", pyside)
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", qtcore)
    monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", qtwidgets)

    ui_package = ModuleType("ui")
    ui_package.__path__ = [str(ROOT / "ui")]
    monkeypatch.setitem(sys.modules, "ui", ui_package)

    def load(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    bridge = load("ui.bridge", ROOT / "ui" / "bridge.py")
    multi = load("ui.multi_session_bridge", ROOT / "ui" / "multi_session_bridge.py")
    return bridge, multi


class _FakeController:
    def __init__(self) -> None:
        self.settings = Settings(language="it", audio_source="system")
        self.backend = SimpleNamespace(is_running=False)
        self.buffer = SimpleNamespace(buffer_level=17)
        self.subscriptions = {}
        self.started = []
        self.updated = []

    def subscribe(self, event, handler) -> None:
        self.subscriptions.setdefault(event, []).append(handler)

    def list_models(self):
        return [{"model": "medium", "installed": True}]

    def list_playback_streams(self):
        return [
            {
                "id": 42,
                "display_name": "Browser — Video",
                "state": "playing",
                "process_id": 123,
                "process_binary": "browser",
                "sink_name": "sink.main",
            }
        ]

    def list_live_sessions(self, include_text=False):
        payload = {
            "id": "live-1",
            "status": "running",
            "terminal": False,
            "source": "system",
            "buffer_level": 12,
        }
        if include_text:
            payload["text"] = "ciao"
        return [payload]

    def is_running(self):
        return True

    def is_draining(self):
        return False

    def is_file_transcribing(self):
        return False

    def start_live_session(self, **kwargs):
        self.started.append(kwargs)
        return {"id": "new-session"}

    def update_settings(self, **overrides):
        self.updated.append(overrides)
        self.settings = self.settings.with_(**overrides)

    def prune_history(self):
        return 0


def test_bootstrap_contains_real_multi_session_runtime(monkeypatch) -> None:
    bridge_module, multi_module = _load_bridges(monkeypatch)
    controller = _FakeController()
    monkeypatch.setattr(
        bridge_module,
        "list_available_devices",
        lambda: [{"name": "monitor", "is_monitor": True, "is_mic": False}],
    )

    bridge = multi_module.MultiSessionBackendBridge(controller)
    payload = json.loads(bridge.getBootstrap())

    assert payload["settings"]["language"] == "it"
    assert payload["devices"][0]["name"] == "monitor"
    assert payload["playbackStreams"][0]["id"] == 42
    assert payload["liveSessions"][0]["text"] == "ciao"
    assert payload["runtime"]["liveSessionCount"] == 1
    assert payload["runtime"]["liveRunning"] is True
    assert payload["runtime"]["bufferLevel"] == 17


def test_bridge_forwards_session_event_as_json(monkeypatch) -> None:
    _, multi_module = _load_bridges(monkeypatch)
    controller = _FakeController()
    bridge = multi_module.MultiSessionBackendBridge(controller)
    received = []
    bridge.eventReceived.connect(lambda name, payload: received.append((name, json.loads(payload))))

    handler = controller.subscriptions["live_session_updated"][0]
    handler({"id": "live-1", "status": "draining"})

    assert received == [
        ("live_session_updated", {"id": "live-1", "status": "draining"})
    ]


def test_probe_application_source_returns_playing_stream(monkeypatch) -> None:
    _, multi_module = _load_bridges(monkeypatch)
    controller = _FakeController()
    bridge = multi_module.MultiSessionBackendBridge(controller)

    response = json.loads(bridge.probeAudioSource("application", "42"))

    assert response["status"] == "playing"
    assert response["stream"]["id"] == 42


def test_start_live_application_converts_selection_to_stream_id(monkeypatch) -> None:
    _, multi_module = _load_bridges(monkeypatch)
    controller = _FakeController()
    bridge = multi_module.MultiSessionBackendBridge(controller)
    monkeypatch.setattr(
        bridge,
        "_run_async",
        lambda name, operation, error_event: operation(),
    )

    bridge.startLive("application", "42", "en")

    assert controller.started == [
        {
            "sink_name": None,
            "audio_source": "application",
            "language": "en",
            "stream_id": 42,
        }
    ]


def test_apply_settings_round_trip_uses_controller_validation(monkeypatch) -> None:
    _, multi_module = _load_bridges(monkeypatch)
    controller = _FakeController()
    bridge = multi_module.MultiSessionBackendBridge(controller)

    response = json.loads(bridge.applySettings(json.dumps({"language": "en", "beam_size": 7})))

    assert response["ok"] is True
    assert response["settings"]["language"] == "en"
    assert response["settings"]["beam_size"] == 7
    assert controller.updated[-1] == {"language": "en", "beam_size": 7}


def test_settings_defaults_are_generated_from_settings_model(monkeypatch) -> None:
    _, multi_module = _load_bridges(monkeypatch)
    bridge = multi_module.MultiSessionBackendBridge(_FakeController())

    defaults = json.loads(bridge.getSettingsDefaults())

    assert defaults["model_size"] == Settings().model_size
    assert defaults["window_width"] == Settings().window_width
    assert defaults["window_height"] == Settings().window_height
