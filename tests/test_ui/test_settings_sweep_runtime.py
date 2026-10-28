"""Settings audits using real keyboard editing, application and persistence."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from conftest import visual_child, wait_until
from config.settings import Settings


def type_text(window, field, text):
    field.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    for char in text:
        QTest.keyClick(window, Qt.Key(ord(char.upper())))


def test_language_edit_from_keyboard_is_saved_and_survives_geometry_events(quick_window):
    app, window, service, controller, messages = quick_window
    root = window._window
    root.setProperty("view", "settings")
    app.processEvents()
    field = visual_child(root.contentItem(), "languageField")
    assert field.property("text") == "en"
    type_text(root, field, "it")
    assert window.runtime.settings._draft["language"] == "it"
    service.persist_window_geometry(10, 20, 1300, 850)
    app.processEvents()
    assert field.property("text") == "it"
    window.runtime.settings.save()
    wait_until(lambda: not window.runtime.settings.saving)
    assert controller.settings.language == "it"
    assert Settings.load().language == "it"
    assert field.property("text") == "it"


def test_meeting_language_edit_survives_unrelated_setting_updates(quick_window):
    app, window, service, _controller, _messages = quick_window
    root = window._window
    root.setProperty("view", "meeting")
    app.processEvents()
    field = visual_child(root.contentItem(), "meetingLanguageField")
    assert field.property("text") == "en"
    type_text(root, field, "it")
    assert field.property("text") == "it"
    service.persist_window_geometry(10, 20, 1300, 850)
    app.processEvents()
    assert field.property("text") == "it"


import pytest
from PySide6.QtCore import QObject

TEXT_SETTINGS = [
    ("language", "it", "it", False),
    ("history_retention_days", "0", 0, False),
    ("meeting_audio_retention_days", "7", 7, False),
    ("beam_size", "3", 3, True), ("vad_min_silence_ms", "200", 200, True),
    ("buffer_warn_threshold", "7", 7, True), ("chunk_ms", "500", 500, True),
    ("sink_name", "testinput", "testinput", True),
    ("sink_search_keyword", "usb", "usb", True),
    ("server_port", "18092", 18092, True),
    ("backend_instances", "2", 2, True),
]


@pytest.mark.parametrize("key,text,expected,advanced", TEXT_SETTINGS)
def test_every_text_preference_can_be_edited_saved_and_reloaded(quick_window, key, text, expected, advanced):
    app, window, service, controller, messages = quick_window
    root = window._window
    root.setProperty("view", "settings")
    root.findChild(QObject, "settingsPage").setProperty("advanced", advanced)
    app.processEvents()
    field = visual_child(root.contentItem(), key + "Field")
    type_text(root, field, text)
    assert window.runtime.settings.dirty
    visual_child(root.contentItem(), "saveSettingsButton").clicked.emit()
    wait_until(lambda: not window.runtime.settings.saving)
    assert getattr(controller.settings, key) == expected
    assert getattr(Settings.load(), key) == expected
    assert not window.runtime.settings.dirty
    assert window.runtime.settings.applied[key] == expected
    assert not any("TypeError" in message or "ReferenceError" in message for message in messages)


@pytest.mark.parametrize("key,index,expected,advanced", [
    ("model_size", 1, "large-v3-turbo", False),
    ("audio_source", 2, "microphone", False),
    ("channels", 1, 2, True),
    ("dictation_activation_mode", 1, "toggle", False),
    ("dictation_insertion_mode", 1, "final", False),
])
def test_every_choice_is_saved_and_reaches_its_consumer(quick_window, key, index, expected, advanced):
    app, window, service, controller, messages = quick_window
    root = window._window
    root.setProperty("view", "settings")
    root.findChild(QObject, "settingsPage").setProperty("advanced", advanced)
    app.processEvents()
    choice = visual_child(root.contentItem(), key + "Control")
    choice.setProperty("currentIndex", index)
    choice.activated.emit(index)
    if key != "model_size": window.runtime.settings.save()
    wait_until(lambda: not window.runtime.settings.saving)
    assert getattr(controller.settings, key) == expected
    assert getattr(Settings.load(), key) == expected
    if key == "channels": assert controller.settings.chunk_samples == 48000
    if key == "dictation_insertion_mode": assert service.dictation_insertion_mode() == "final"
    if key == "dictation_activation_mode": assert controller._dictation_activation.snapshot()["mode"] == "toggle"
    if key == "audio_source": wait_until(lambda: window.runtime.sources.source == "microphone")


@pytest.mark.parametrize("key,control,advanced", [("vad_filter", "vadFilterToggle", False),
                                                 ("preload_model", "preloadModelToggle", True)])
def test_toggles_save_real_booleans(quick_window, key, control, advanced):
    app, window, _, controller, _ = quick_window
    root = window._window
    root.setProperty("view", "settings")
    root.findChild(QObject, "settingsPage").setProperty("advanced", advanced)
    app.processEvents()
    toggle = visual_child(root.contentItem(), control)
    expected = not getattr(controller.settings, key)
    toggle.setProperty("checked", expected)
    toggle.toggled.emit()
    window.runtime.settings.save()
    wait_until(lambda: not window.runtime.settings.saving)
    assert getattr(Settings.load(), key) is expected


@pytest.mark.parametrize("key", ["gpu_layers", "compute_type", "device", "sample_rate", "dtype"])
def test_fixed_engine_fields_do_not_pretend_to_be_editable(quick_window, key):
    app, window, _, _, _ = quick_window
    window._window.setProperty("view", "settings")
    window._window.findChild(QObject, "settingsPage").setProperty("advanced", True)
    app.processEvents()
    assert visual_child(window._window.contentItem(), key + "Field").property("readOnly")


@pytest.mark.parametrize("workflow", ["live", "files", "meeting"])
def test_each_job_language_survives_defaults_and_window_updates(quick_window, workflow):
    app, window, service, controller, _ = quick_window
    root = window._window
    view = "file" if workflow == "files" else workflow
    root.setProperty("view", view)
    app.processEvents()
    name = "fileLanguageField" if workflow == "files" else workflow + "LanguageField"
    field = visual_child(root.contentItem(), name)
    type_text(root, field, "it")
    service.persist_window_geometry(10, 20, 1300, 850)
    app.processEvents()
    assert field.property("text") == "it"
    assert getattr(window.runtime, workflow).language == "it"
    assert controller.settings.language == "en"
    getattr(window.runtime, workflow).resetLanguage()
    app.processEvents()
    assert field.property("text") == "en"


def test_unsaved_defaults_are_not_advertised_or_used_as_applied(quick_window, monkeypatch):
    app, window, service, controller, _ = quick_window
    settings = window.runtime.settings
    settings.edit("language", "it")
    assert settings.values["language"] == "it" and settings.applied["language"] == "en"
    called = []
    monkeypatch.setattr(service, "start_live", lambda *args: called.append(args))
    window.runtime.live.start(False)
    assert not called and "Salva" in window.runtime.feedback.message
    settings.save()
    wait_until(lambda: not settings.saving)
    window.runtime.live.start(False)
    assert called[0][2] == "it" and controller.settings.language == "it"


def test_empty_numeric_field_does_not_become_zero_or_get_saved(quick_window):
    app, window, _, controller, _ = quick_window
    window.runtime.settings.edit("vad_min_silence_ms", "")
    window.runtime.settings.save()
    assert controller.settings.vad_min_silence_ms == 500
    assert window.runtime.settings.dirty and window.runtime.feedback.message


def test_queued_file_uses_explicit_job_language_without_changing_default(quick_window, tmp_path, monkeypatch):
    app, window, service, controller, _ = quick_window
    path = tmp_path / "sample.wav"; path.write_bytes(b"audio fixture")
    captured = []
    monkeypatch.setattr(controller, "start_file_transcription", lambda *args, **kwargs: captured.append(kwargs))
    files = window.runtime.files
    files.set_paths([str(path)])
    files.editLanguage("it")
    files.start(False, False)
    wait_until(lambda: bool(captured))
    assert captured[0]["language"] == "it"
    assert service.file_batch.list_jobs()[0]["language"] == "it"
    assert controller.settings.language == "en"


def test_live_and_meeting_start_receive_the_edited_language(quick_window, monkeypatch):
    app, window, service, controller, _ = quick_window
    live, meeting = [], []
    monkeypatch.setattr(controller, "start_live_session", lambda **kwargs: live.append(kwargs))
    monkeypatch.setattr(controller.meeting, "start_realtime", lambda *args, **kwargs: meeting.append(kwargs))
    window.runtime.live.editLanguage("it")
    window.runtime.live.start(False)
    wait_until(lambda: bool(live))
    window.runtime.meeting.editLanguage("it")
    window.runtime.meeting.start(False, window.runtime.meeting.language, 0)
    assert live[0]["language"] == "it" and meeting[0]["language"] == "it"


def test_dictation_busy_prevents_settings_save(quick_window, monkeypatch):
    app, window, service, controller, _ = quick_window
    monkeypatch.setattr(controller, "dictation_busy", lambda: True)
    window.runtime._event("dictation_session_changed", {"status": "listening", "requested": True})
    assert window.runtime.busy
    with pytest.raises(RuntimeError, match="dettatura"):
        service.apply_settings({"language": "it"})
    assert controller.settings.language == "en"


def test_ui_sweep_covers_every_editable_global_preference():
    from ui.adapters.settings import SECTIONS
    covered = {key for key, *_ in TEXT_SETTINGS} | {"model_size", "audio_source", "channels",
               "dictation_activation_mode", "dictation_insertion_mode", "vad_filter", "preload_model"}
    assert covered == set().union(*SECTIONS.values())


@pytest.mark.parametrize("section", ["recognition", "history", "dictation", "audio", "tuning", "backend"])
def test_reset_changes_only_the_selected_section(quick_window, section):
    from dataclasses import asdict
    from ui.adapters.settings import SECTIONS
    app, window, service, controller, _ = quick_window
    changes = {"language": "it", "history_retention_days": 0, "dictation_insertion_mode": "final",
               "chunk_ms": 500, "beam_size": 3, "server_port": 18092}
    service.apply_settings(changes)
    app.processEvents()
    before = asdict(controller.settings)
    window.runtime.settings.reset(section)
    wait_until(lambda: not window.runtime.settings.saving)
    after = asdict(controller.settings)
    defaults = asdict(Settings())
    for key in set().union(*SECTIONS.values()):
        assert after[key] == (defaults[key] if key in SECTIONS[section] else before[key])
    assert asdict(Settings.load()) == after


def test_reset_does_not_discard_another_sections_unsaved_language(quick_window):
    app, window, _, controller, _ = quick_window
    window.runtime.settings.edit("language", "it")
    window.runtime.settings.reset("history")
    wait_until(lambda: not window.runtime.settings.saving)
    assert window.runtime.settings.values["language"] == "it"
    assert window.runtime.settings.applied["language"] == "en"
    assert window.runtime.settings.dirty


def test_default_language_follows_saved_settings_only_until_overridden(quick_window):
    app, window, service, _, _ = quick_window
    service.apply_settings({"language": "it"})
    app.processEvents()
    assert all(a.language == "it" for a in (window.runtime.live, window.runtime.files, window.runtime.meeting))
    window.runtime.files.editLanguage("fr")
    service.apply_settings({"language": "en"})
    app.processEvents()
    assert window.runtime.files.language == "fr"
    assert window.runtime.live.language == window.runtime.meeting.language == "en"
    window.runtime.files.resetLanguage()
    assert window.runtime.files.language == "en"


def test_recording_choice_survives_geometry_notifications(quick_window):
    app, window, service, _, _ = quick_window
    window.runtime.sources.setSource("microphone")
    app.processEvents()
    toggle = visual_child(window._window.contentItem(), "liveRecordToggle")
    toggle.setProperty("checked", True)
    toggle.toggled.emit()
    service.persist_window_geometry(10, 20, 1300, 850)
    app.processEvents()
    assert toggle.property("checked") and window.runtime.live.recordAudio


def test_in_progress_queue_displays_its_language_instead_of_next_jobs_override(quick_window):
    app, window, _, _, _ = quick_window
    window.runtime.files.queue.replace([{"id": "one", "status": "running", "language": "en", "model_size": "medium"}])
    window.runtime.files.editLanguage("it")
    assert window.runtime.files.activeLanguage == "en"
    assert window.runtime.files.activeModel == "medium"
    assert window.runtime.files.language == "it"


def test_shorter_retention_removes_only_expired_test_artifacts(quick_window):
    import json
    import os
    import time
    from config.constants import AppMeta
    app, window, service, controller, _ = quick_window
    sid = controller.history.create_session(kind="file", model="large-v3", language="it")
    controller.history.set_status(sid, "completed", terminal=True)
    path = controller.history.root / (sid + ".json")
    data = json.loads(path.read_text())
    data["started_at"] = data["updated_at"] = data["ended_at"] = "2000-01-01T00:00:00+00:00"
    path.write_text(json.dumps(data))
    service.apply_settings({"history_retention_days": 1})
    assert controller.history.get_session(sid) is None
    meeting = controller.meeting.store.create(model="large-v3", language="it", source="file",
                                               source_path="fixture.wav", acquisition_mode="file")
    AppMeta.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    audio = AppMeta.RECORDINGS_DIR / (meeting + ".flac")
    audio.write_bytes(b"expired fixture")
    controller.meeting.store.set_recording(meeting, {"path": str(audio), "format": "flac"})
    os.utime(audio, (time.time() - 10*86400, time.time() - 10*86400))
    service.apply_settings({"meeting_audio_retention_days": 1})
    assert not audio.exists()
    assert controller.meeting.get(meeting) is not None


def test_file_output_remains_readable_at_minimum_window_size(quick_window):
    from PySide6.QtCore import QObject
    app, window, _, _, _ = quick_window
    root = window._window
    root.setProperty("view", "file")
    root.setWidth(1200); root.setHeight(800)
    app.processEvents()
    page = root.findChild(QObject, "filePage")
    output = root.findChild(QObject, "fileTranscriptCard")
    assert output.property("height") >= 180
    assert page.property("contentHeight") >= page.property("availableHeight")
