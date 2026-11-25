import threading

from conftest import visual_child, wait_until
from PySide6.QtCore import QObject, QPointF

from tests.test_ui.test_qml_runtime import seed_meeting
from ui.adapters.meeting import MeetingAdapter


def test_meeting_draft_keeps_language_and_speaker_fields_editable(quick_window):
    app, window, _service, _controller, messages = quick_window
    window._window.setProperty("view", "meeting")
    page = window._window.findChild(QObject, "meetingPage")
    page.setProperty("fromFile", True)
    adapter = window.runtime.meeting
    adapter._english_status_received({"ready": True, "busy": False})
    adapter.drafts.replace(
        [
            {
                "path": "public.wav",
                "language": "en",
                "num_speakers": 0,
                "pipeline": "qwen_meeting",
            }
        ]
    )
    root = window._window.contentItem()
    wait_until(lambda: visual_child(root, "draftLanguage0") is not None)
    app.processEvents()
    language = visual_child(root, "draftLanguage0")
    speakers = visual_child(root, "draftSpeakers0")
    pipeline = visual_child(root, "draftPipeline0")
    assert language.width() >= 50
    assert speakers.width() >= 50
    assert pipeline.width() >= 150
    assert not language.property("readOnly")
    assert language.property("selectedValue") == "en"
    assert not any("TypeError" in m or "ReferenceError" in m for m in messages)


def test_english_status_only_refreshes_general_bindings_when_busy_changes(quick_window):
    _app, window, _service, _controller, _messages = quick_window
    adapter = window.runtime.meeting
    general, english = [], []
    adapter.changed.connect(lambda: general.append(True))
    adapter.englishChanged.connect(lambda: english.append(True))
    adapter._english_status_received({"ready": True, "busy": False})
    adapter._english_status_received({"ready": True, "busy": False, "progress": 50})
    assert general == []
    assert len(english) == 2
    adapter._english_status_received({"ready": True, "busy": True})
    adapter._english_status_received({"ready": True, "busy": True, "progress": 75})
    adapter._english_status_received({"ready": True, "busy": False})
    assert len(general) == 2


def test_recovered_timing_warning_is_visible_in_review(quick_window):
    _app, window, service, controller, _messages = quick_window
    sid = seed_meeting(controller)
    meeting = service.get_meeting(sid)["meeting"]
    rows = meeting["review_segments"]
    rows[0]["quality_recovery"] = {"timing_requires_review": True}
    rows[0]["alignment_warnings"] = ["approximate_recovered_timing"]
    controller.meeting.store.set_diarization(
        sid, diarization_segments=meeting["diarization_segments"], review_segments=rows
    )
    adapter = window.runtime.meeting
    adapter.select(sid)
    wait_until(lambda: adapter.segments.count == 2)
    assert "tempi approssimativi" in adapter.segments.get(0)["quality_note"]


def test_recovered_timing_warning_is_visible_in_archive(quick_window):
    _app, window, _service, controller, _messages = quick_window
    sid = seed_meeting(controller)
    controller.history.append_quality_issues(
        sid,
        [
            {
                "reason": "overlap_boundary_recovered",
                "start": 62,
                "end": 65,
                "recovered": False,
                "timing_requires_review": True,
            }
        ],
    )
    archive = window.runtime.archive
    archive.select(sid)
    wait_until(lambda: archive.selected.get("id") == sid)
    assert "Parole recuperate; tempi approssimativi" in archive.qualityDetails
    assert "01:02–01:05" in archive.qualityDetails


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
        "name",
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
    assert "Salvataggio in corso" in meeting.draftStatus
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
    wait_until(
        lambda: (
            service.get_meeting(sid)["meeting"]["review_segments"][1]["text"]
            == "ultima battuta"
        )
    )
    assert service.get_meeting(sid)["meeting"]["review_drafts"] == {}


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
    wait_until(lambda: visual_child(root, "reviewEditor0") is not None)
    app.processEvents()
    editor = visual_child(root, "reviewEditor0")
    row = visual_child(root, "reviewSegment0")
    bottom = editor.mapToItem(row, QPointF(0, editor.height())).y()
    assert bottom <= row.height() - 7
    assert visual_child(root, "reviewSave0") is None  # autosave needs no per-row button
    assert not any("Binding loop" in message for message in messages)


def test_history_exposes_persisted_quality_locations_after_reopening(quick_window):
    _app, window, _service, controller, _messages = quick_window
    sid = controller.history.create_session(
        kind="file", model="large-v3", language="it"
    )
    controller.history.append_quality_issues(
        sid,
        [
            {
                "reason": "repetition_loop",
                "start": 62,
                "end": 74,
                "recovered": False,
            }
        ],
    )
    archive = window.runtime.archive
    archive.select(sid)
    wait_until(lambda: archive.selected.get("id") == sid)
    assert "01:02–01:14" in archive.qualityDetails
    assert "Ripetizione sospetta" in archive.qualityDetails
    assert "Da riascoltare" in archive.qualityDetails
