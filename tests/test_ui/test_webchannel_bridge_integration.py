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


class _QUrl:
    def __init__(self, value: str = "") -> None:
        self.value = value

    @classmethod
    def fromLocalFile(cls, value: str):
        return cls(f"file://{value}")

    def toString(self) -> str:
        return self.value


class _QTimer:
    @staticmethod
    def singleShot(_delay, callback):
        callback()


class _QFileDialog:
    @staticmethod
    def getOpenFileName(*args, **kwargs):
        del args, kwargs
        return "", ""

    @staticmethod
    def getOpenFileNames(*args, **kwargs):
        del args, kwargs
        return [], ""

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
    qtcore.QUrl = _QUrl
    qtcore.QTimer = _QTimer
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
    unified = load("ui.phase10_bridge", ROOT / "ui" / "phase10_bridge.py")
    return bridge, unified


class _FakeController:
    def __init__(self) -> None:
        self.settings = Settings(language="it", audio_source="system")
        self.backend = SimpleNamespace(is_running=False, reconfigure=lambda _settings: None)
        self.buffer = SimpleNamespace(buffer_level=17)
        self.history = SimpleNamespace(search=lambda *_args: [], list_recent=lambda *_args: [])
        self.file_batch = SimpleNamespace(list_jobs=lambda: [])
        self.meeting = SimpleNamespace(
            snapshot=lambda: None,
            is_busy=lambda: False,
            models=SimpleNamespace(status=lambda: {"ready": False}),
        )
        self.subscriptions = {}
        self.started = []
        self.updated = []
        self.discovery_requests = []
        self.probe_requests = []
        self.discovery_devices = [
            {"name": "monitor", "is_monitor": True, "is_mic": False}
        ]
        self.discovery_streams = [
            {
                "id": 42,
                "display_name": "Browser — Video",
                "state": "playing",
                "process_id": 123,
                "process_binary": "browser",
                "sink_name": "sink.main",
            }
        ]

    def subscribe(self, event, handler) -> None:
        self.subscriptions.setdefault(event, []).append(handler)

    def list_models(self):
        return [{"id": "medium", "model": "medium", "installed": True}]

    def list_playback_streams(self):
        return list(self.discovery_streams)

    def audio_discovery_snapshot(self):
        return {
            "devices": list(self.discovery_devices),
            "streams": list(self.discovery_streams),
        }

    def request_audio_discovery(self, *, devices=True, streams=True):
        self.discovery_requests.append((devices, streams))

    def cached_audio_source_health(self, source, selected_input=""):
        if source == "application" and selected_input == "42":
            return {
                "source": source,
                "selected_input": selected_input,
                "status": "playing",
                "label": "In riproduzione",
                "detail": "Browser — Video",
                "stream": self.discovery_streams[0],
                "streams": 1,
            }
        return {
            "source": source,
            "selected_input": selected_input,
            "status": "disconnected",
            "label": "Verifica in corso",
            "detail": "Controllo della sorgente audio in background.",
        }

    def request_audio_source_probe(self, source, selected_input=""):
        self.probe_requests.append((source, selected_input))

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

    def active_live_count(self):
        return 0

    def is_running(self):
        return True

    def is_draining(self):
        return False

    def is_file_transcribing(self):
        return False

    def is_file_busy(self):
        return False

    def start_live_session(self, **kwargs):
        self.started.append(kwargs)
        return {"id": "new-session"}

    def update_settings(self, **overrides):
        self.updated.append(overrides)
        self.settings = self.settings.with_(**overrides)

    def prune_history(self):
        return 0

    def stop_backend(self):
        self.backend.is_running = False


def test_bootstrap_contains_real_multi_session_runtime(monkeypatch) -> None:
    _, unified_module = _load_bridges(monkeypatch)
    controller = _FakeController()

    bridge = unified_module.Phase10BackendBridge(controller)
    payload = json.loads(bridge.getBootstrap())

    assert payload["settings"]["language"] == "it"
    assert payload["devices"][0]["name"] == "monitor"
    assert payload["playbackStreams"][0]["id"] == 42
    assert payload["liveSessions"][0]["text"] == "ciao"
    assert payload["runtime"]["liveSessionCount"] == 1
    assert payload["runtime"]["liveRunning"] is True
    assert payload["runtime"]["bufferLevel"] == 17
    assert payload["runtime"]["meetingBusy"] is False
    assert controller.discovery_requests[-1] == (True, True)


def test_bridge_forwards_session_event_as_json(monkeypatch) -> None:
    _, unified_module = _load_bridges(monkeypatch)
    controller = _FakeController()
    bridge = unified_module.Phase10BackendBridge(controller)
    received = []
    bridge.eventReceived.connect(lambda name, payload: received.append((name, json.loads(payload))))

    handler = controller.subscriptions["live_session_updated"][0]
    handler({"id": "live-1", "status": "draining"})

    assert received == [
        ("live_session_updated", {"id": "live-1", "status": "draining"})
    ]


def test_probe_application_source_returns_cache_and_schedules_refresh(monkeypatch) -> None:
    _, unified_module = _load_bridges(monkeypatch)
    controller = _FakeController()
    bridge = unified_module.Phase10BackendBridge(controller)

    response = json.loads(bridge.probeAudioSource("application", "42"))

    assert response["status"] == "playing"
    assert response["stream"]["id"] == 42
    assert controller.probe_requests == [("application", "42")]


def test_start_live_application_converts_selection_to_stream_id(monkeypatch) -> None:
    _, unified_module = _load_bridges(monkeypatch)
    controller = _FakeController()
    bridge = unified_module.Phase10BackendBridge(controller)
    monkeypatch.setattr(
        bridge,
        "_run_async",
        lambda name, operation, error_event: operation(),
    )
    monkeypatch.setattr(bridge, "_prepare_backend_for_selected_model", lambda: None)

    bridge.startLive("application", "42", "en")

    assert controller.started == [
        {
            "sink_name": None,
            "audio_source": "application",
            "language": "en",
            "stream_id": 42,
            "record_audio": False,
        }
    ]


def test_apply_settings_round_trip_uses_controller_validation(monkeypatch) -> None:
    _, unified_module = _load_bridges(monkeypatch)
    controller = _FakeController()
    bridge = unified_module.Phase10BackendBridge(controller)

    response = json.loads(bridge.applySettings(json.dumps({"language": "en", "beam_size": 7})))

    assert response["ok"] is True
    assert response["settings"]["language"] == "en"
    assert response["settings"]["beam_size"] == 7
    assert controller.updated[-1] == {"language": "en", "beam_size": 7}


def test_settings_defaults_are_generated_from_settings_model(monkeypatch) -> None:
    _, unified_module = _load_bridges(monkeypatch)
    bridge = unified_module.Phase10BackendBridge(_FakeController())

    defaults = json.loads(bridge.getSettingsDefaults())

    assert defaults["model_size"] == Settings().model_size
    assert defaults["window_width"] == Settings().window_width
    assert defaults["window_height"] == Settings().window_height
    assert defaults["live_microphone_recording"] is False
    assert defaults["meeting_audio_retention_days"] == 30
