"""Real Qt editing, autosave/undo and three review presentations."""

import threading

import pytest
from conftest import visual_child, wait_until
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from tests.test_ui.test_qml_runtime import seed_meeting
from ui.adapters.meeting import MeetingAdapter


def test_opening_archive_scrolls_after_async_review_expands_layout(quick_window):
    app, window, _service, controller, _messages = quick_window
    sid = seed_meeting(controller, 50)
    root = window._window
    root.setProperty("view", "meeting")
    window.runtime.archive.refresh()
    wait_until(lambda: window.runtime.archive.meetings.count == 1)
    assert QTest.qWaitForWindowExposed(root)
    QTest.qWait(50)
    wait_until(lambda: visual_child(root.contentItem(), "recentMeetingOpen0") is not None)
    button = visual_child(root.contentItem(), "recentMeetingOpen0")
    assert button is not None
    point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2))
    QTest.mouseClick(root, Qt.MouseButton.LeftButton, pos=point.toPoint())
    wait_until(lambda: window.runtime.meeting.review.get("id") == sid)
    page = root.findChild(QObject, "meetingPage")
    viewport = page.property("contentItem")
    wait_until(lambda: viewport.property("contentY") > 100)
    wait_until(lambda: not page.property("reviewRequested"))
    QTest.qWait(300)
    review = root.findChild(QObject, "meetingCorrectionsCard")
    assert review.mapToScene(QPointF(0, 0)).y() < root.height() / 2


def test_fifty_edits_autosave_without_manual_confirmation_and_reload(quick_window):
    _app, window, service, controller, _messages = quick_window
    sid = seed_meeting(controller, 50)
    meeting = window.runtime.meeting
    meeting.select(sid)
    wait_until(lambda: meeting.segments.count == 50)
    for index in range(50):
        meeting.editText(index, f"Correzione persistente {index}")
    assert "Salvataggio in corso" in meeting.draftStatus
    wait_until(lambda: not meeting.dirty and not meeting.saving)
    assert meeting.draftStatus == "Tutte le modifiche salvate"
    replacement = MeetingAdapter(service, window.runtime.feedback)
    replacement.select(sid)
    try:
        wait_until(lambda: replacement.segments.count == 50)
        assert [r["text"] for r in replacement.segments.rows()] == [
            f"Correzione persistente {i}" for i in range(50)
        ]
        replacement.undo()
        wait_until(lambda: not replacement.saving)
        assert replacement.segments.get(49)["text"] == "segmento 49"
        replacement.redo()
        wait_until(lambda: not replacement.saving)
        assert replacement.segments.get(49)["text"] == "Correzione persistente 49"
    finally:
        replacement.close()


def test_manual_review_scrollbar_suspends_audio_follow(quick_window):
    _app, window, _service, controller, _messages = quick_window
    seed_meeting(controller, 50)
    root = window._window
    root.setProperty("view", "meeting")
    window.runtime.archive.refresh()
    wait_until(lambda: window.runtime.archive.meetings.count == 1)
    assert QTest.qWaitForWindowExposed(root)
    QTest.qWait(50)
    wait_until(lambda: visual_child(root.contentItem(), "recentMeetingOpen0") is not None)
    button = visual_child(root.contentItem(), "recentMeetingOpen0")
    point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2))
    QTest.mouseClick(root, Qt.MouseButton.LeftButton, pos=point.toPoint())
    page = root.findChild(QObject, "meetingPage")
    wait_until(lambda: page.property("contentItem").property("contentY") > 100)
    listing = root.findChild(QObject, "meetingReviewList")
    modes = root.findChild(QObject, "reviewEditorModes")
    bar = visual_child(root.contentItem(), "reviewScrollBar")
    assert modes.property("following")
    start = bar.mapToScene(QPointF(bar.width() / 2, bar.property("size") * bar.height() / 2))
    end = start + QPointF(0, 60)
    QTest.mousePress(root, Qt.MouseButton.LeftButton, pos=start.toPoint())
    QTest.mouseMove(root, end.toPoint())
    QTest.mouseRelease(root, Qt.MouseButton.LeftButton, pos=end.toPoint())
    wait_until(lambda: listing.property("contentY") > 0)
    assert not modes.property("following")
    position = listing.property("contentY")
    window.runtime.meeting.setPlaybackPosition(80)
    QTest.qWait(100)
    assert listing.property("contentY") == pytest.approx(position, abs=1)


def test_language_keyboard_choice_scrolls_into_view_and_commits_code(quick_window):
    _app, window, _service, _controller, _messages = quick_window
    root = window._window
    root.setProperty("view", "file")
    combo = root.findChild(QObject, "fileLanguageField")
    assert QTest.qWaitForWindowExposed(root)
    QTest.qWait(50)
    combo.forceActiveFocus()
    QTest.keyClick(root, Qt.Key.Key_Space)
    wait_until(lambda: visual_child(root.contentItem(), "fileLanguageFieldChoices") is not None)
    QTest.keyClick(root, Qt.Key.Key_End)
    assert QTest.qWaitForWindowExposed(root)
    QTest.qWait(50)
    listing = visual_child(root.contentItem(), "fileLanguageFieldChoices")
    wait_until(lambda: listing.property("currentIndex") == combo.property("count") - 1)
    selected = listing.property("currentItem")
    assert selected is not None and selected.property("highlighted")
    label = selected.property("contentItem")
    wait_until(lambda: (
        label.mapToItem(listing, QPointF(0, 0)).y() >= 0
        and label.mapToItem(listing, QPointF(0, 0)).y() + label.height() <= listing.height() + 1
    ))
    QTest.keyClick(root, Qt.Key.Key_Return)
    assert window.runtime.files.language == combo.property("currentValue")
    assert window.runtime.files.language == combo.property("selectedValue")


@pytest.mark.parametrize("mode", ["compact", "columns", "document"])
def test_three_layouts_share_edits_and_follow_does_not_steal_editor_focus(
    quick_window, mode
):
    app, window, service, controller, messages = quick_window
    root = window._window
    meeting = window.runtime.meeting
    sid = seed_meeting(controller, 50)
    root.setProperty("view", "meeting")
    meeting.select(sid)
    wait_until(lambda: meeting.segments.count == 50)
    modes = root.findChild(QObject, "reviewEditorModes")
    modes.setProperty("mode", mode)
    app.processEvents()
    editor = visual_child(root.contentItem(), "reviewEditor0")
    assert editor is not None
    editor.forceActiveFocus()
    assert not modes.property("following")
    QTest.keyClick(root, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    for letter in "testo corretto":
        QTest.keyClick(root, Qt.Key(ord(letter.upper())))
    wait_until(lambda: not meeting.dirty and not meeting.saving)
    assert (
        service.get_meeting(sid)["meeting"]["review_segments"][0]["text"]
        == "testo corretto"
    )
    meeting.setPlaybackPosition(70)
    app.processEvents()
    assert editor.hasActiveFocus()
    assert modes.property("selectedIndex") == 0
    QTest.keyClick(root, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    wait_until(lambda: not meeting.saving)
    assert meeting.segments.get(0)["text"] == "segmento 0"
    QTest.keyClick(root, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    wait_until(lambda: not meeting.saving)
    assert meeting.segments.get(0)["text"] == "testo corretto"
    assert not any(
        "TypeError" in m or "ReferenceError" in m or "Binding loop" in m
        for m in messages
    ), messages


def test_failed_autosave_never_reports_saved_or_discards_the_draft(
    quick_window, monkeypatch
):
    _app, window, service, controller, _messages = quick_window
    sid = seed_meeting(controller)
    meeting = window.runtime.meeting
    meeting.select(sid)
    wait_until(lambda: meeting.segments.count == 2)
    original = service.edit_meeting_segments

    def fail(*_args):
        raise OSError("Disk full")

    monkeypatch.setattr(service, "edit_meeting_segments", fail)
    meeting.editText(0, "Da conservare")
    wait_until(lambda: bool(meeting._save_error))
    assert meeting.dirty and "Errore di salvataggio" in meeting.draftStatus
    assert (
        service.get_meeting(sid)["meeting"]["review_segments"][0]["text"]
        == "segmento 0"
    )
    monkeypatch.setattr(service, "edit_meeting_segments", original)
    meeting.saveAll()
    wait_until(lambda: not meeting.dirty and not meeting.saving)
    assert meeting.draftStatus == "Tutte le modifiche salvate"


def test_speaker_actions_queued_behind_slow_save_are_not_dropped(
    quick_window, monkeypatch
):
    _app, window, service, controller, _messages = quick_window
    sid = seed_meeting(controller)
    meeting = window.runtime.meeting
    meeting.select(sid)
    wait_until(lambda: meeting.segments.count == 2)
    entered, release = threading.Event(), threading.Event()
    original = service.edit_meeting_segments

    def delayed(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)

    monkeypatch.setattr(service, "edit_meeting_segments", delayed)
    meeting.editText(0, "Prima modifica")
    meeting.saveAll()
    wait_until(entered.is_set)
    meeting.renameSpeaker("SPEAKER_01", "Voce 2")
    meeting.setSpeaker(0, "SPEAKER_01")
    meeting.renameSpeaker("SPEAKER_01", "Nuovo nome")
    release.set()
    wait_until(lambda: not meeting.saving and not meeting._write_queue)
    metadata = service.get_meeting(sid)["meeting"]
    assert metadata["review_segments"][0]["speaker_override"] == "SPEAKER_01"
    assert metadata["speaker_names"]["SPEAKER_01"] == "Nuovo nome"


def test_follow_handles_multiple_active_speakers_and_backward_seek(quick_window):
    _app, window, service, controller, _messages = quick_window
    sid = seed_meeting(controller)
    meeting = window.runtime.meeting
    meeting.select(sid)
    wait_until(lambda: meeting.segments.count == 2)
    meeting.setPlaybackPosition(0.5)
    assert meeting.activeIndices == [0]
    meeting.setPlaybackPosition(2.5)
    assert meeting.activeIndices == [1]
    meeting.setPlaybackPosition(0.5)
    assert meeting.activeIndices == [0]


def test_live_follows_appends_and_respects_manual_reading_and_selection(quick_window):
    app, window, _service, _controller, messages = quick_window
    root = window._window
    root.setProperty("view", "live")
    live = window.runtime.live
    text = "\n".join(
        f"Riga trascritta {i}: il testo deve restare leggibile." for i in range(180)
    )
    live.hydrate(
        [{"id": "scroll-test", "source": "microphone", "text": text, "terminal": False}]
    )
    wait_until(
        lambda: (
            visual_child(root.contentItem(), "liveTranscriptscroll-test") is not None
        )
    )
    transcript = visual_child(root.contentItem(), "liveTranscriptscroll-test")
    viewport = transcript.findChild(QObject, "transcriptViewport")
    area = transcript.findChild(QObject, "transcriptText")
    wait_until(lambda: viewport.property("contentY") > 500)
    assert transcript.property("following")
    area.forceActiveFocus()
    QTest.keyClick(root, Qt.Key.Key_Home, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert not transcript.property("following")
    viewport.setProperty("contentY", 50)
    area.select(3, 10)
    live.handle_event(
        "live_session_text",
        {"session_id": "scroll-test", "text": "Nuovo chunk aggiunto"},
    )
    app.processEvents()
    assert area.property("selectionStart") == 3 and area.property("selectionEnd") == 10
    assert viewport.property("contentY") == pytest.approx(50)
    area.deselect()
    transcript.followLatest()
    app.processEvents()
    assert viewport.property("contentY") > 500
    assert not any(
        "TypeError" in m or "ReferenceError" in m or "Binding loop" in m
        for m in messages
    ), messages


def test_changing_meeting_waits_for_autosave_then_navigates_without_manual_save(quick_window):
    _app, window, service, controller, _messages = quick_window
    first = seed_meeting(controller)
    second = seed_meeting(controller)
    meeting = window.runtime.meeting
    meeting.select(first)
    wait_until(lambda: meeting.review.get('id') == first)
    meeting.editText(0, 'Correzione prima di cambiare')
    meeting.select(second)
    wait_until(lambda: meeting.review.get('id') == second)
    assert service.get_meeting(first)['meeting']['review_segments'][0]['text'] == 'Correzione prima di cambiare'
