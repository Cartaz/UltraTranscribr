import json
from pathlib import Path

from core.dictation_portal_state import DictationPortalStateStore


def test_portal_state_round_trip_and_clear(tmp_path: Path):
    path = tmp_path / "portal.json"
    store = DictationPortalStateStore(path)
    assert store.restore_token() is None
    store.set_restore_token("opaque-token")
    assert store.restore_token() == "opaque-token"
    store.set_restore_token(None)
    assert store.restore_token() is None
    assert not path.exists()


def test_portal_state_malformed_or_wrong_type_is_ignored(tmp_path: Path):
    path = tmp_path / "portal.json"
    path.write_text("{broken", encoding="utf-8")
    assert DictationPortalStateStore(path).restore_token() is None
    path.write_text(json.dumps({"remote_desktop_restore_token": 42}), encoding="utf-8")
    assert DictationPortalStateStore(path).restore_token() is None


def test_portal_state_rejects_empty_or_oversized_token(tmp_path: Path):
    store = DictationPortalStateStore(tmp_path / "portal.json")
    for value in ("", "x" * 8193):
        try:
            store.set_restore_token(value)
        except ValueError:
            pass
        else:
            raise AssertionError("token non valido accettato")
