import pytest

from config.settings import DictationActivationMode, DictationInsertionMode, Settings


def test_dictation_defaults_are_push_to_talk_and_live():
    settings = Settings()
    assert settings.dictation_activation_mode == DictationActivationMode.PUSH_TO_TALK.value
    assert settings.dictation_insertion_mode == DictationInsertionMode.LIVE.value


def test_dictation_modes_are_validated():
    with pytest.raises(ValueError):
        Settings(dictation_activation_mode="invalid")
    with pytest.raises(ValueError):
        Settings(dictation_insertion_mode="invalid")


def test_dictation_modes_round_trip_through_with():
    settings = Settings().with_(
        dictation_activation_mode="toggle",
        dictation_insertion_mode="final",
    )
    assert settings.dictation_activation_mode == "toggle"
    assert settings.dictation_insertion_mode == "final"


def test_portal_restore_token_is_not_a_public_setting():
    assert "dictation_remote_restore_token" not in Settings.__dataclass_fields__
