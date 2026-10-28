"""Every preference is validated, persisted, and applied at its actual boundary."""
import json
import threading
from dataclasses import asdict
from unittest.mock import Mock

import pytest

from config.constants import AppMeta
from config.settings import BOOLEAN_FIELDS, INTEGER_FIELDS, Settings
from core.app_controller import AppController
from core.event_bus import EventBus

VALID = {
    "sample_rate": 16000, "channels": 2, "chunk_ms": 500, "dtype": "float32",
    "model_size": "medium", "device": "sycl", "compute_type": "f16", "language": " IT ",
    "audio_source": "microphone", "beam_size": 3, "vad_filter": False,
    "vad_min_silence_ms": 200, "buffer_warn_threshold": 7,
    "history_retention_days": 0, "meeting_audio_retention_days": 0,
    "live_microphone_recording": True, "sink_name": " forced.input ", "sink_search_keyword": "USB",
    "gpu_layers": 99, "server_port": 18092, "backend_instances": 2, "preload_model": True,
    "dictation_activation_mode": "toggle", "dictation_insertion_mode": "final",
    "window_x": -100, "window_y": 50, "window_width": 1400, "window_height": 900,
}


def test_sweep_covers_every_persisted_preference():
    assert set(VALID) == set(Settings.__dataclass_fields__)


@pytest.mark.parametrize("key,value", VALID.items())
def test_every_setting_round_trips_without_resetting_other_fields(key, value):
    settings = Settings(language="it").with_(**{key: value})
    settings.save()
    assert asdict(Settings.load()) == asdict(settings)
    assert settings.language == "it"


@pytest.mark.parametrize("key", sorted(INTEGER_FIELDS))
@pytest.mark.parametrize("value", [True, 1.5, float("nan"), float("inf"), "1"])
def test_numeric_preferences_cannot_save_ambiguous_types(key, value):
    with pytest.raises(ValueError, match=key):
        Settings(**{key: value})


@pytest.mark.parametrize("key", sorted(BOOLEAN_FIELDS))
@pytest.mark.parametrize("value", ["false", 0, 1, None])
def test_boolean_preferences_are_not_truthy_strings_or_numbers(key, value):
    with pytest.raises(ValueError, match=key):
        Settings(**{key: value})


@pytest.mark.parametrize("key,value", [("compute_type", "f32"), ("gpu_layers", 0),
                                      ("sample_rate", 8000), ("dtype", "int16"), ("device", "cpu")])
def test_unavailable_engine_options_are_rejected_instead_of_ignored(key, value):
    with pytest.raises(ValueError, match=key):
        Settings().with_(**{key: value})


@pytest.mark.parametrize("language,expected", [(" IT ", "it"), ("en-US", "en"), ("it-IT", "it"), ("auto", "auto")])
def test_language_is_canonical_before_any_inference(language, expected):
    assert Settings(language=language).language == expected


@pytest.mark.parametrize("language", ["xx", "italiano", "", "en, it", None])
def test_invalid_language_cannot_silently_revert_to_english(language):
    with pytest.raises(ValueError):
        Settings(language=language)


def test_one_corrupt_preference_does_not_reset_the_saved_language():
    AppMeta.CONFIG_DIR.mkdir(parents=True)
    AppMeta.SETTINGS_PATH.write_text(json.dumps({"language": "it", "model_size": "medium",
                                               "beam_size": 0, "vad_filter": "false"}))
    loaded = Settings.load()
    assert loaded.language == "it" and loaded.model_size == "medium"
    assert loaded.beam_size == Settings().beam_size
    assert loaded.vad_filter is True


@pytest.mark.parametrize("key", ["window_x", "window_y", "window_width", "window_height"])
@pytest.mark.parametrize("value", [True, 1.5, float("nan"), float("inf"), float("-inf"), "invalid"])
def test_corrupt_window_preference_preserves_language_and_recovers(key, value):
    AppMeta.CONFIG_DIR.mkdir(parents=True)
    AppMeta.SETTINGS_PATH.write_text(json.dumps({"language": "it", key: value}))
    loaded = Settings.load()
    assert loaded.language == "it"
    assert getattr(loaded, key) == getattr(Settings(), key)


def controller():
    app = AppController.__new__(AppController)
    app._settings = Settings(language="en")
    app._settings_update_lock = threading.RLock()
    app._settings_applying = threading.Event()
    app._backend_init_lock = threading.Lock()
    app._bus = EventBus()
    app._backend = Mock(is_running=False)
    app._backend_started = False
    app._backend_model_size = None
    app.dictation_busy = lambda: False
    app.active_live_count = lambda: 0
    app.is_file_busy = lambda: False
    app._dictation_activation = Mock()
    app._meeting = Mock()
    app._history = Mock()
    app._history.prune_older_than.return_value = 0
    app._meeting.prune_audio.return_value = 0
    app._settings.save()
    return app


def test_failed_save_does_not_change_runtime_or_disk_language(monkeypatch):
    app = controller()
    old = AppMeta.SETTINGS_PATH.read_bytes()
    def fail(_self):
        raise OSError("disk full")
    monkeypatch.setattr(Settings, "save", fail)
    with pytest.raises(OSError, match="disk full"):
        app.update_settings(language="it")
    assert app.settings.language == "en"
    assert AppMeta.SETTINGS_PATH.read_bytes() == old


def test_geometry_autosave_and_language_change_are_serialized(monkeypatch):
    app = controller()
    entered, release, second_started = threading.Event(), threading.Event(), threading.Event()
    original = Settings.save
    failures = []
    def save(settings):
        if settings.language == "it" and settings.window_width == 1200:
            entered.set()
            assert release.wait(3)
        original(settings)
    monkeypatch.setattr(Settings, "save", save)
    def language():
        try: app.update_settings(language="it")
        except Exception as exc: failures.append(exc)
    def geometry():
        second_started.set()
        try: app.update_settings(window_width=1400)
        except Exception as exc: failures.append(exc)
    one = threading.Thread(target=language)
    two = threading.Thread(target=geometry)
    one.start()
    assert entered.wait(2)
    two.start()
    assert second_started.wait(2)
    release.set()
    one.join(3); two.join(3)
    assert not one.is_alive() and not two.is_alive() and not failures
    assert (app.settings.language, app.settings.window_width) == ("it", 1400)
    assert (Settings.load().language, Settings.load().window_width) == ("it", 1400)


def test_backend_failure_cannot_publish_or_persist_new_settings():
    app = controller()
    app._backend.reconfigure.side_effect = [RuntimeError("backend failed"), None]
    with pytest.raises(RuntimeError, match="backend failed"):
        app.apply_settings(beam_size=2)
    assert app.settings.beam_size == 5 and Settings.load().beam_size == 5
    assert app._backend.reconfigure.call_args.args[0].beam_size == 5


def test_persistence_failure_restores_previous_backend_profile(monkeypatch):
    app = controller()
    def fail(_self): raise OSError("disk full")
    monkeypatch.setattr(Settings, "save", fail)
    with pytest.raises(OSError): app.apply_settings(server_port=18092)
    assert app.settings.server_port == 8082
    assert [call.args[0].server_port for call in app._backend.reconfigure.call_args_list] == [18092, 8082]


def test_all_backend_options_reach_the_backend_and_new_whisper_command():
    from core.whisper_backend import WhisperBackend
    app = controller()
    settings = app.apply_settings(model_size="medium", beam_size=3, vad_filter=True,
                                  vad_min_silence_ms=200, server_port=18092, backend_instances=2)
    assert app._backend.reconfigure.call_args.args[0] == settings
    backend = WhisperBackend(settings)
    backend._server_binary = "whisper-server"
    backend._vad_model_path = AppMeta.MODELS_DIR / "vad.bin"
    command = backend._build_cmd(AppMeta.MODELS_DIR / "medium.bin", True)
    assert command[command.index("--beam-size") + 1] == "3"
    assert command[command.index("--port") + 1] == "18092"
    assert command[command.index("--vad-min-silence-duration-ms") + 1] == "200"
    assert backend._settings.backend_instances == 2


def test_retention_and_dictation_changes_invoke_their_real_consumers():
    app = controller()
    app.update_settings(history_retention_days=10, meeting_audio_retention_days=4,
                        dictation_activation_mode="toggle")
    app._history.prune_older_than.assert_called_once_with(10)
    app._meeting.prune_audio.assert_called_once()
    app._dictation_activation.set_mode.assert_called_once_with("toggle")


def test_forced_device_is_used_by_capture_resolution_and_health(monkeypatch):
    from core.sink_finder import find_source
    from core.audio_discovery import AudioDiscoveryService
    settings = Settings(sink_name="forced.input")
    assert find_source(settings, "microphone") == "forced.input"
    assert find_source(settings, "system") == "forced.input"
    # This path must not consult a different default device for its status.
    health = AudioDiscoveryService.__new__(AudioDiscoveryService)
    assert health._resolve_automatic_source(settings, "microphone") == "forced.input"


@pytest.mark.parametrize("value", [True, 0.5, float("nan"), float("inf"), -1, 21, "bad"])
def test_speaker_count_cannot_silently_turn_a_fraction_into_automatic(value):
    from core.meeting_engine import speaker_count
    with pytest.raises(ValueError, match="intero"):
        speaker_count(value)


@pytest.mark.parametrize("value,expected", [(0, 0), ("2", 2), (2.0, 2), (20, 20)])
def test_speaker_count_accepts_explicit_integer_values(value, expected):
    from core.meeting_engine import speaker_count
    assert speaker_count(value) == expected


def test_global_dictation_shortcut_cannot_start_mid_settings_transition():
    app = controller()
    app._dictation = Mock()
    app._settings_applying.set()
    app._handle_dictation_event("dictation_activation_changed", {"active": True})
    app._dictation_activation.cancel.assert_called_once()
    app._dictation.set_active.assert_not_called()


def test_failed_backend_change_releases_the_settings_transition_guard():
    app = controller()
    app._backend.reconfigure.side_effect = [RuntimeError("failed"), None]
    with pytest.raises(RuntimeError): app.apply_settings(beam_size=3)
    assert not app._settings_applying.is_set()
