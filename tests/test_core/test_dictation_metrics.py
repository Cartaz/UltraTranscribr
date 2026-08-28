from core.dictation_metrics import DictationMetricsTracker


def test_metrics_preserve_missing_insert_as_none():
    now = [10.0]
    tracker = DictationMetricsTracker(clock=lambda: now[0])
    tracker.observe("dictation_activation_changed", {"active": True})
    now[0] = 10.2
    tracker.observe("dictation_session_changed", {"status": "listening"})
    now[0] = 11.0
    tracker.observe("dictation_text_committed", "hello")
    now[0] = 11.2
    tracker.observe("dictation_session_changed", {"status": "finalizing"})
    now[0] = 11.5
    sample = tracker.observe("dictation_session_changed", {"status": "idle"})
    assert sample is not None
    assert sample.activation_to_first_insert_ms is None
    assert round(sample.activation_to_first_commit_ms or 0) == 1000
    assert round(sample.finalization_ms or 0) == 300


def test_queue_wait_tracks_maximum():
    now = [0.0]
    tracker = DictationMetricsTracker(clock=lambda: now[0])
    tracker.observe("dictation_activation_changed", {"active": True})
    tracker.observe("dictation_queue_wait", 12.5)
    tracker.observe("dictation_queue_wait", 80.0)
    now[0] = 1.0
    sample = tracker.observe("dictation_session_changed", {"status": "idle"})
    assert sample is not None
    assert sample.max_queue_wait_ms == 80.0
