"""Runtime regressions for QML adapters against the real application and stores."""

import threading
import wave

from conftest import visual_child, wait_until
from PySide6.QtCore import QObject, Qt, QThread, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest

from ui.models import RecordModel
from ui.native.dictation_overlay import DictationOverlay


def test_audio_player_load_seek_mute_speed_and_source_reset(quick_window, tmp_path):
    """Real decoder/control path; no sound device or inference is required."""
    _app, window, _service, _controller, messages = quick_window
    audio = visual_child(window._window.contentItem(), "meetingAudioPlayer")
    player = audio.findChild(QMediaPlayer, "audioMediaPlayer")
    output = audio.findChild(QAudioOutput, "audioOutput")
    path = tmp_path / "silence.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 32000)
    assert audio.clock(65000) == "1:05"
    assert not visual_child(audio, "audioPlayButton").isEnabled()
    rerun = window._window.findChild(QObject, "meetingRerunButton")
    assert not rerun.property("enabled")
    audio.seek(10)
    assert audio.property("pendingSeek") == -1
    audio.setProperty("source", QUrl.fromLocalFile(str(path)))
    audio.seek(2)
    wait_until(lambda: player.duration() == 4000)
    wait_until(lambda: player.position() == 2000)
    audio.seek(-5)
    assert player.position() == 2000
    audio.seek(500)
    assert player.position() == 4000
    assert visual_child(audio, "audioPlayButton").isEnabled()
    visual_child(audio, "audioMuteButton").clicked.emit()
    assert output.isMuted()
    visual_child(audio, "audioMuteButton").clicked.emit()
    assert not output.isMuted()
    slider = audio.findChild(QObject, "audioVolumeSlider")
    slider.setProperty("value", 0.3)
    slider.moved.emit()
    assert abs(output.volume() - 0.3) < 0.001
    audio.findChild(QObject, "audioSpeed1.5").triggered.emit()
    assert player.playbackRate() == 1.5
    seek = visual_child(audio, "audioSeekSlider")
    seek.setProperty("value", 1000)
    seek.moved.emit()
    assert player.position() == 1000
    audio.setProperty("source", QUrl())
    wait_until(lambda: player.source().isEmpty())
    assert not audio.property("playing") and audio.property("pendingSeek") == -1
    assert not visual_child(audio, "audioPlayButton").isEnabled()
    assert not any("TypeError" in m or "ReferenceError" in m for m in messages)


def seed_meeting(controller, count=2):
    store = controller.meeting.store
    sid = store.create(
        model="large-v3",
        language="it",
        source="file",
        source_path="fixture.wav",
        acquisition_mode="file",
    )
    controller.history.append_text(sid, "Testo originale immutabile")
    store.set_diarization(
        sid,
        diarization_segments=[],
        review_segments=[
            {
                "start": i * 2.0,
                "end": i * 2.0 + 1.0,
                "speaker_id": "SPEAKER_00",
                "text": f"segmento {i}",
            }
            for i in range(count)
        ],
    )
    store.set_speaker_name(sid, "SPEAKER_00", "Speaker 1")
    store.set_status(sid, "completed", terminal=True)
    return sid


def test_record_model_retains_identity_and_copies_nested_values():
    model = RecordModel([{"id": "a", "nested": {"value": 1}}])
    resets = []
    model.modelReset.connect(lambda: resets.append(True))
    row = model.get(0)
    row["nested"]["value"] = 99
    assert model.get(0)["nested"]["value"] == 1
    model.upsert({"id": "a", "text": "updated"})
    assert model.count == 1 and model.get(0)["text"] == "updated" and not resets
    model.update(0, index=7)
    assert model.get(0)["index"] == 7
    assert model.get(-1) == {} and model.get(100) == {}


def test_worker_events_are_delivered_on_gui_thread(quick_window):
    app, window, _service, _controller, _messages = quick_window
    live = window.runtime.live
    threads = []
    live.changed.connect(lambda: threads.append(QThread.currentThread()))

    def worker():
        window.runtime.eventArrived.emit(
            "live_session_created", {"id": "fixture", "terminal": False, "text": ""}
        )
        window.runtime.eventArrived.emit(
            "live_session_text", {"session_id": "fixture", "text": "ciao"}
        )
        window.runtime.eventArrived.emit(
            "live_session_buffer_level", {"session_id": "fixture", "level": 48}
        )
        window.runtime.eventArrived.emit(
            "live_session_queue_wait",
            {"session_id": "fixture", "wait_ms": 12, "peak_ms": 30},
        )

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    wait_until(
        lambda: (
            live.sessions.count == 1 and live.sessions.get(0).get("queue_wait_ms") == 12
        )
    )
    assert live.sessions.get(0)["text"] == "ciao"
    assert live.sessions.get(0)["buffer_level"] == 48
    assert threads and all(t == app.thread() for t in threads)


def test_discovery_keeps_missing_selection_and_ignores_stale_health(quick_window):
    sources = quick_window[1].runtime.sources
    sources.setSource("microphone")
    sources.select("missing-device")
    sources.set_devices([{"name": "other", "is_mic": True}])
    assert sources.selected == "missing-device"
    sources.set_health(
        {"source": "system", "selected_input": "missing-device", "available": True}
    )
    assert sources.health.get("source") != "system"
    sources.set_health(
        {"source": "microphone", "selected_input": "missing-device", "available": False}
    )
    assert sources.health["available"] is False


def test_settings_normalization_and_immediate_model_selection(quick_window):
    settings = quick_window[1].runtime.settings
    service = quick_window[2]
    settings.edit("channels", "1")
    settings.save()
    wait_until(lambda: not settings.saving)
    assert settings.values["channels"] == 1 and "channels" not in settings._draft
    settings.selectModel("medium")
    wait_until(lambda: not settings.saving)
    assert service.bootstrap_snapshot()["settings"]["model_size"] == "medium"


def test_invalid_settings_report_error_without_losing_draft(quick_window):
    settings = quick_window[1].runtime.settings
    feedback = quick_window[1].runtime.feedback
    settings.edit("language", "invalid-language")
    settings.save()
    wait_until(lambda: not settings.saving)
    assert settings._draft["language"] == "invalid-language" and feedback.message


def test_model_errors_release_operation_state(quick_window):
    settings = quick_window[1].runtime.settings
    settings.handle_event("model_download_started", {"model": "medium"})
    assert settings.modelBusy == "medium"
    settings.handle_event(
        "model_download_error", {"model": "medium", "error": "disk full"}
    )
    assert not settings.modelBusy
    settings.handle_event("model_delete_error", {"model": "medium"})
    assert not settings.modelBusy


def test_history_reads_derived_strings_and_persists_rename(quick_window):
    _app, window, _service, controller, _messages = quick_window
    sid = controller.history.create_session(
        kind="file", model="medium", language="it", source_path="fixture.wav"
    )
    controller.history.append_text(sid, "testo originale")
    controller.history.save_derived_output(sid, "clean", "testo corretto")
    archive = window.runtime.archive
    archive.select(sid)
    wait_until(lambda: archive.selected.get("id") == sid)
    archive.setProfile("clean")
    assert archive.text == "testo corretto"
    archive.rename("Nome prova")
    wait_until(lambda: archive.selected.get("name") == "Nome prova")
    assert controller.history.get_session(sid)["name"] == "Nome prova"
    archive.search("Nome prova")
    wait_until(lambda: archive.history.count == 1)
    assert archive.history.get(0)["id"] == sid
    archive.deleteSession(sid)
    wait_until(lambda: not archive.selected)
    assert controller.history.get_session(sid) is None


def test_drop_rejects_remote_urls_and_preserves_local_files(quick_window, tmp_path):
    files = quick_window[1].runtime.files
    path = tmp_path / "sample.wav"
    path.write_bytes(b"fixture")
    files.dropFiles(
        ["https://example.com/sample.wav", QUrl.fromLocalFile(str(path)).toString()]
    )
    assert files._paths == [str(path)]


def test_single_segment_save_keeps_other_drafts_and_raw_text(quick_window):
    _app, window, service, controller, _messages = quick_window
    sid = seed_meeting(controller)
    meeting = window.runtime.meeting
    meeting._load_review(service.get_meeting(sid))
    meeting.editText(0, "primo corretto")
    meeting.editText(1, "secondo corretto")
    meeting.saveSegment(0)
    wait_until(lambda: not meeting.saving)
    assert meeting._edits == {1: "secondo corretto"} and meeting.dirty
    meeting.saveAll()
    wait_until(lambda: not meeting.saving)
    assert not meeting.dirty and not window._meeting_review_dirty
    saved = service.get_meeting(sid)
    assert saved["text"] == "Testo originale immutabile"
    assert [r["text"] for r in saved["meeting"]["review_segments"]] == [
        "primo corretto",
        "secondo corretto",
    ]


def test_edits_during_pending_save_survive_completion(quick_window, monkeypatch):
    _app, window, service, controller, _messages = quick_window
    sid = seed_meeting(controller)
    meeting = window.runtime.meeting
    meeting._load_review(service.get_meeting(sid))
    entered = threading.Event()
    release = threading.Event()
    original = service.edit_meeting_segments

    def delayed(session, edits):
        entered.set()
        assert release.wait(3)
        return original(session, edits)

    monkeypatch.setattr(service, "edit_meeting_segments", delayed)
    meeting.editText(0, "prima versione")
    meeting.saveAll()
    try:
        wait_until(entered.is_set)
        meeting.editText(0, "nuova versione")
    finally:
        release.set()
    wait_until(lambda: not meeting.saving)
    assert meeting._edits == {0: "nuova versione"}
    assert meeting.segments.get(0)["draft_text"] == "nuova versione"
    assert (
        service.get_meeting(sid)["meeting"]["review_segments"][0]["text"]
        == "prima versione"
    )


def test_failed_save_preserves_edits_and_clears_busy(quick_window, monkeypatch):
    _app, window, service, controller, _messages = quick_window
    meeting = window.runtime.meeting
    meeting._load_review(service.get_meeting(seed_meeting(controller)))

    def fail(*args):
        raise OSError("Disk full")

    monkeypatch.setattr(service, "edit_meeting_segments", fail)
    meeting.editText(0, "non perdere")
    meeting.saveAll()
    wait_until(lambda: not meeting.saving)
    assert meeting.dirty and meeting.segments.get(0)["draft_text"] == "non perdere"
    assert "Disk full" in window.runtime.feedback.message


def test_real_keyboard_edits_survive_delegate_recycling(quick_window):
    app, window, service, controller, messages = quick_window
    meeting = window.runtime.meeting
    meeting._load_review(service.get_meeting(seed_meeting(controller, 150)))
    root = window._window
    root.setProperty("view", "meeting")
    app.processEvents()
    wait_until(lambda: visual_child(root.contentItem(), "reviewEditor0") is not None)
    editor = visual_child(root.contentItem(), "reviewEditor0")
    editor.forceActiveFocus()
    QTest.keyClick(root, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    for char in "correzione persistente":
        QTest.keyClick(
            root, Qt.Key(ord(char.upper())) if char != " " else Qt.Key.Key_Space
        )
    wait_until(lambda: meeting._edits.get(0) == "correzione persistente")
    view = root.findChild(QObject, "meetingReviewList")
    view.setProperty("contentY", 12000)
    app.processEvents()
    view.setProperty("contentY", 0)
    app.processEvents()
    wait_until(lambda: visual_child(root.contentItem(), "reviewEditor0") is not None)
    assert (
        visual_child(root.contentItem(), "reviewEditor0").property("text")
        == "correzione persistente"
    )
    assert not any("TypeError" in m or "ReferenceError" in m for m in messages), (
        messages
    )


def test_overlay_never_takes_focus_and_disposes_idempotently(quick_window):
    overlay = DictationOverlay()
    try:
        flags = overlay._window.flags()
        assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
        assert flags & Qt.WindowType.WindowTransparentForInput
        overlay.update_state("listening")
        assert overlay.isVisible()
        overlay.update_state("idle")
        assert not overlay.isVisible()
    finally:
        overlay.close()
        overlay.close()


def test_default_source_setting_updates_live_picker(quick_window):
    window = quick_window[1]
    settings = window.runtime.settings
    settings.edit("audio_source", "microphone")
    settings.save()
    wait_until(
        lambda: not settings.saving and window.runtime.sources.source == "microphone"
    )


def test_speaker_override_can_return_to_automatic_without_losing_text_draft(
    quick_window,
):
    _app, window, service, controller, _messages = quick_window
    sid = seed_meeting(controller)
    meeting = window.runtime.meeting
    meeting._load_review(service.get_meeting(sid))
    meeting.editText(0, "correzione non salvata")
    meeting.setSpeaker(0, "SPEAKER_00")
    wait_until(lambda: not meeting.saving)
    assert meeting.segments.get(0)["speaker_choice"] == "SPEAKER_00"
    meeting.setSpeaker(0, "")
    wait_until(lambda: not meeting.saving)
    assert meeting.segments.get(0)["speaker_choice"] == ""
    assert meeting.segments.get(0)["speaker_options"][0]["value"] == ""
    assert meeting.segments.get(0)["draft_text"] == "correzione non salvata"


def test_delayed_postprocess_does_not_replace_new_history_selection(
    quick_window, monkeypatch
):
    app, window, service, controller, _messages = quick_window
    first = seed_meeting(controller)
    second = seed_meeting(controller)
    archive = window.runtime.archive
    archive.select(first)
    wait_until(lambda: archive.selected.get("id") == first)
    entered = threading.Event()
    release = threading.Event()

    def delayed(session, profile):
        entered.set()
        assert release.wait(3)
        controller.history.save_derived_output(session, profile, "generato")

    monkeypatch.setattr(service, "generate_postprocess", delayed)
    archive.generate("clean")
    try:
        wait_until(entered.is_set)
        archive.select(second)
        wait_until(lambda: archive.selected.get("id") == second)
    finally:
        release.set()
    wait_until(lambda: service._tasks.active_count == 0)
    app.processEvents()
    assert archive.selected["id"] == second and archive.profile == "raw"


def test_raw_profile_is_available_in_real_picker(quick_window):
    _app, window, _service, _controller, _messages = quick_window
    archive = window.runtime.archive
    assert archive.profiles.get(0) == {"id": "raw", "label": "Originale"}
    assert {r["id"] for r in archive.profiles.rows()} == {"raw", "clean", "paragraphs"}


def test_long_review_can_scroll_to_all_content(quick_window):
    app, window, service, controller, messages = quick_window
    window.runtime.meeting._load_review(
        service.get_meeting(seed_meeting(controller, 150))
    )
    window._window.setProperty("view", "meeting")
    app.processEvents()
    page = window._window.findChild(QObject, "meetingPage")
    wait_until(lambda: page.property("contentHeight") > page.property("height"))
    flick = page.property("contentItem")
    flick.setProperty("contentY", 600)
    app.processEvents()
    assert flick.property("contentY") > 500
    assert not any(
        "Binding loop" in m or "recursive rearrange" in m for m in messages
    ), messages


def test_user_supplied_labels_are_rendered_as_plain_text(quick_window):
    app, window, _service, controller, _messages = quick_window
    sid = seed_meeting(controller)
    label = "<b>Nome letterale</b>"
    controller.history.set_name(sid, label)
    window.runtime.archive.select(sid)
    wait_until(lambda: window.runtime.archive.selected.get("id") == sid)
    window._window.setProperty("view", "history")
    app.processEvents()
    matching = [
        item
        for item in window._window.findChildren(QObject)
        if item.metaObject().className() == "QQuickText"
        and item.property("text") == label
    ]
    assert matching
    for item in matching:
        expression = QQmlExpression(
            QQmlEngine.contextForObject(item), item, "textFormat === 0"
        )
        result = expression.evaluate()
        assert not expression.hasError()
        assert result[0] if isinstance(result, tuple) else result
