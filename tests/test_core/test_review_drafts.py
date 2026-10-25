import json

from core.meeting_store import MeetingStore
from core.transcript_history import TranscriptHistoryStore


def seeded(tmp_path):
    history = TranscriptHistoryStore(tmp_path / "history")
    store = MeetingStore(history, tmp_path / "meetings")
    sid = store.create(
        model="large-v3", language="it", source="file", source_path="fixture.wav"
    )
    store.set_diarization(
        sid,
        diarization_segments=[],
        review_segments=[
            {
                "start": 0,
                "end": 1,
                "raw_text": "originale",
                "text": "originale",
                "speaker_id": None,
            }
        ],
    )
    return history, store, sid


def snapshot(store, sid, text):
    metadata = store.get(sid)["meeting"]
    row = metadata["review_segments"][0]
    return {
        0: {
            "text": text,
            "base_text": row["text"],
            "review_key": metadata["review_keys"][0],
        }
    }


def test_drafts_survive_store_restart_without_overwriting_approved_or_raw_text(
    tmp_path,
):
    history, store, sid = seeded(tmp_path)
    store.save_review_drafts(
        sid, snapshot(store, sid, "correzione da confermare"), "process-a", 1
    )
    restarted = MeetingStore(history, store.root)
    recovered = restarted.get(sid)["meeting"]
    assert recovered["review_drafts"] == {"0": "correzione da confermare"}
    assert recovered["review_segments"][0]["text"] == "originale"
    assert recovered["review_segments"][0]["raw_text"] == "originale"


def test_stale_background_checkpoint_cannot_resurrect_discarded_drafts(tmp_path):
    _, store, sid = seeded(tmp_path)
    old = snapshot(store, sid, "vecchia bozza")
    store.save_review_drafts(sid, {}, "process-a", 3)
    store.save_review_drafts(sid, old, "process-a", 2)
    assert store.get(sid)["meeting"]["review_drafts"] == {}


def test_draft_for_changed_segment_is_preserved_as_conflict_not_applied(tmp_path):
    _, store, sid = seeded(tmp_path)
    store.save_review_drafts(
        sid, snapshot(store, sid, "correzione importante"), "process-a", 1
    )
    store.set_diarization(
        sid,
        diarization_segments=[],
        review_segments=[
            {
                "start": 0,
                "end": 2,
                "raw_text": "altro segmento",
                "text": "altro segmento",
            }
        ],
    )
    recovered = store.get(sid)["meeting"]
    assert recovered["review_drafts"] == {}
    assert recovered["draft_conflicts"][0]["text"] == "correzione importante"
    store.save_review_drafts(sid, {}, "process-b", 1)
    assert (
        store.get(sid)["meeting"]["draft_conflicts"][0]["text"]
        == "correzione importante"
    )


def test_damaged_draft_does_not_hide_transcript_or_get_silently_overwritten(tmp_path):
    _, store, sid = seeded(tmp_path)
    path = store._draft_path(sid)
    path.parent.mkdir(parents=True)
    path.write_text('{"edits":')
    recovered = store.get(sid)["meeting"]
    assert recovered["review_segments"][0]["text"] == "originale"
    assert recovered["draft_recovery_error"]
    assert path.read_text() == '{"edits":'


def test_valid_json_with_wrong_draft_schema_still_leaves_canonical_text_readable(
    tmp_path,
):
    _, store, sid = seeded(tmp_path)
    path = store._draft_path(sid)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"edits": {"0": "not a draft object"}}))
    recovered = store.get(sid)["meeting"]
    assert recovered["review_segments"][0]["text"] == "originale"
    assert recovered["draft_recovery_error"]


def test_confirmed_draft_is_not_restored_as_an_unsaved_edit(tmp_path):
    _, store, sid = seeded(tmp_path)
    store.save_review_drafts(sid, snapshot(store, sid, "approvata"), "process-a", 1)
    store.edit_review_segment(sid, 0, "approvata")
    assert not store.get(sid)["meeting"]["review_drafts"]
    assert not store.get(sid)["meeting"]["draft_conflicts"]
