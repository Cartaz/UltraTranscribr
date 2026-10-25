import threading

from conftest import visual_child, wait_until
from PySide6.QtCore import QPointF

from tests.test_ui.test_qml_runtime import seed_meeting
from ui.adapters.meeting import MeetingAdapter


def test_long_review_does_not_send_document_through_qvariant_on_every_edit(
    quick_window,
):
    _app, window, _service, controller, _messages = quick_window
    sid = seed_meeting(controller, 2389)
    meeting = window.runtime.meeting
    meeting.select(sid)
    wait_until(lambda: meeting.segments.count == 2389)
    assert set(meeting.review) == {
        "id",
        "started_at",
        "text",
        "full_text",
        "meeting",
        "quality_notice",
    }
    assert set(meeting.review["meeting"]) == {"num_speakers"}
    notifications = []
    meeting.reviewChanged.connect(lambda: notifications.append(True))
    meeting.editText(0, "correzione")
    meeting.editText(2388, "ultima correzione")
    assert notifications == []
    assert meeting.segments.get(0)["draft_text"] == "correzione"


def test_draft_is_checkpointed_and_restored_without_confirming_it(quick_window):
    _app, window, service, controller, _messages = quick_window
    sid = seed_meeting(controller)
    meeting = window.runtime.meeting
    meeting.select(sid)
    wait_until(lambda: meeting.segments.count == 2)
    meeting.editText(0, "bozza da recuperare")
    wait_until(lambda: not meeting._draft_pending and not meeting._draft_writing)
    assert "protetta" in meeting.draftStatus
    replacement = MeetingAdapter(service, window.runtime.feedback)
    try:
        replacement.select(sid)
        wait_until(lambda: replacement.segments.count == 2)
        assert replacement.dirty
        assert replacement.segments.get(0)["draft_text"] == "bozza da recuperare"
        assert (
            service.get_meeting(sid)["meeting"]["review_segments"][0]["text"]
            == "segmento 0"
        )
    finally:
        replacement.close()


def test_slow_checkpoint_cannot_overwrite_newer_typing_and_has_one_worker(
    quick_window, monkeypatch
):
    _app, window, service, controller, _messages = quick_window
    sid = seed_meeting(controller)
    meeting = window.runtime.meeting
    meeting.select(sid)
    wait_until(lambda: meeting.segments.count == 2)
    original = service.save_meeting_review_drafts
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow(*args):
        calls.append(args)
        if len(calls) == 1:
            entered.set()
            assert release.wait(3)
        return original(*args)

    monkeypatch.setattr(service, "save_meeting_review_drafts", slow)
    meeting.editText(0, "prima")
    wait_until(entered.is_set)
    try:
        for index in range(25):
            meeting.editText(0, f"più recente {index}")
        assert len(calls) == 1
    finally:
        release.set()
    wait_until(lambda: not meeting._draft_pending and not meeting._draft_writing)
    assert service.get_meeting(sid)["meeting"]["review_drafts"] == {
        "0": "più recente 24"
    }
    assert len(calls) == 2


def test_discard_and_final_close_checkpoint_do_not_resurrect_old_edits(quick_window):
    _app, window, service, controller, _messages = quick_window
    sid = seed_meeting(controller)
    meeting = window.runtime.meeting
    meeting.select(sid)
    wait_until(lambda: meeting.segments.count == 2)
    meeting.editText(0, "da annullare")
    wait_until(lambda: not meeting._draft_pending and not meeting._draft_writing)
    meeting.discardEdits()
    meeting.close()  # flushes the clear even before the debounce timer fires
    assert service.get_meeting(sid)["meeting"]["review_drafts"] == {}


def test_immediate_close_flushes_last_edit_before_timer_fires(quick_window):
    _app, window, service, controller, _messages = quick_window
    sid = seed_meeting(controller)
    meeting = window.runtime.meeting
    meeting.select(sid)
    wait_until(lambda: meeting.segments.count == 2)
    meeting.editText(1, "ultima battuta")
    meeting.close()
    assert service.get_meeting(sid)["meeting"]["review_drafts"] == {
        "1": "ultima battuta"
    }


def test_discard_then_immediate_meeting_switch_cannot_restore_discarded_draft(
    quick_window,
):
    _app, window, service, controller, _messages = quick_window
    first, second = seed_meeting(controller), seed_meeting(controller)
    meeting = window.runtime.meeting
    meeting.select(first)
    wait_until(lambda: meeting.review.get("id") == first)
    meeting.editText(0, "da scartare")
    wait_until(lambda: not meeting._draft_pending and not meeting._draft_writing)
    meeting.discardEdits()
    meeting.select(second)  # before the clear timer's 250 ms deadline
    wait_until(lambda: meeting.review.get("id") == second)
    assert service.get_meeting(first)["meeting"]["review_drafts"] == {}
    meeting.select(first)
    wait_until(lambda: meeting.review.get("id") == first)
    assert not meeting.dirty
    assert meeting.segments.get(0)["draft_text"] == "segmento 0"


def test_changed_layout_exposes_recovered_draft_with_its_original_context(quick_window):
    _app, window, service, controller, _messages = quick_window
    sid = seed_meeting(controller)
    stored = service.get_meeting(sid)["meeting"]
    store = controller.meeting.store
    store.save_review_drafts(
        sid,
        {
            0: {
                "text": "correzione da recuperare",
                "base_text": "segmento 0",
                "review_key": stored["review_keys"][0],
            }
        },
        "previous-process",
        1,
    )
    store.set_diarization(
        sid,
        diarization_segments=[],
        review_segments=[
            {
                "start": 0,
                "end": 5,
                "raw_text": "nuovo raggruppamento",
                "text": "nuovo raggruppamento",
            }
        ],
    )
    meeting = window.runtime.meeting
    meeting.select(sid)
    wait_until(lambda: meeting.review.get("id") == sid)
    assert "correzione da recuperare" in meeting.recoveredDraftsText
    assert "segmento 0" in meeting.recoveredDraftsText
    assert not meeting.dirty
    assert meeting.segments.get(0)["draft_text"] == "nuovo raggruppamento"
    assert meeting.segments.get(0)["speaker_name"] == "Speaker ?"


def test_review_save_control_fits_below_uncertainty_and_quality_notice(quick_window):
    app, window, _service, controller, messages = quick_window
    sid = seed_meeting(controller)
    rows = controller.meeting.store.get(sid)["meeting"]["review_segments"]
    rows[0].update(uncertain=True, alignment_warnings=["manual_layout_preserved"])
    controller.meeting.store.set_diarization(
        sid, diarization_segments=[], review_segments=rows
    )
    window._window.setProperty("view", "meeting")
    window.runtime.meeting.select(sid)
    wait_until(lambda: window.runtime.meeting.segments.count == 2)
    root = window._window.contentItem()
    wait_until(lambda: visual_child(root, "reviewSave0") is not None)
    app.processEvents()
    button = visual_child(root, "reviewSave0")
    row = visual_child(root, "reviewSegment0")
    bottom = button.mapToItem(row, QPointF(0, button.height())).y()
    assert bottom <= row.height() - 7
    assert not any("Binding loop" in message for message in messages)


def test_history_exposes_persisted_quality_locations_after_reopening(quick_window):
    _app, window, _service, controller, _messages = quick_window
    sid = controller.history.create_session(kind="file", model="large-v3", language="it")
    controller.history.append_quality_issues(sid, [{
        "reason": "repetition_loop", "start": 62, "end": 74, "recovered": False,
    }])
    archive = window.runtime.archive
    archive.select(sid)
    wait_until(lambda: archive.selected.get("id") == sid)
    assert "01:02–01:14" in archive.qualityDetails
    assert "Ripetizione sospetta" in archive.qualityDetails
    assert "Da riascoltare" in archive.qualityDetails
