from core.dictation_activation import DictationActivationService


def test_push_to_talk_tracks_press_release_once():
    events = []
    service = DictationActivationService("push_to_talk", event_sink=lambda event, payload: events.append((event, payload)))
    service.press(); service.press()
    assert service.snapshot()["active"] is True
    service.release(); service.release()
    assert service.snapshot()["active"] is False
    assert [event for event, _ in events].count("dictation_activation_changed") == 2


def test_toggle_changes_only_on_press():
    service = DictationActivationService("toggle")
    service.press(); service.release()
    assert service.snapshot()["active"] is True
    service.press(); service.release()
    assert service.snapshot()["active"] is False


def test_mode_change_cancels_active_session():
    service = DictationActivationService("push_to_talk")
    service.press()
    service.set_mode("toggle")
    assert service.snapshot()["active"] is False
    assert service.snapshot()["mode"] == "toggle"
