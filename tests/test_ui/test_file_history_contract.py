"""Contracts for the domain-oriented File/History presentation module."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "ui" / "web"


def test_file_history_module_exists_registers_and_is_checked() -> None:
    source = (WEB / "file_history.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    settings = (WEB / "settings_cleanup.js").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "UltraUI.register(fileHistoryModule)" in source
    assert 'src="file_history.js"' in html
    assert 'href="file_history.css"' in html
    assert "file_history.js" not in settings
    assert "node --check ui/web/file_history.js" in workflow
    assert "Legacy" not in source


def test_file_history_module_exposes_batch_search_exports_and_postprocess() -> None:
    source = (WEB / "file_history.js").read_text(encoding="utf-8")
    for token in (
        "chooseAudioFiles",
        "enqueueFileBatch",
        "file_drop_received",
        "searchHistory",
        'fileHistoryExport("srt")',
        'fileHistoryExport("vtt")',
        "generatePostprocess",
        "renameHistorySession",
        "fileHistoryRenderHistory",
        "fileHistoryLoadSession",
        "fileHistoryDeleteSelected",
        "fileHistoryRenderRecovery",
        "fileHistoryRefreshRecovery",
    ):
        assert token in source


def test_history_refresh_preserves_active_search_filter_without_wrapping() -> None:
    source = (WEB / "file_history.js").read_text(encoding="utf-8")
    assert 'const query = $("history-search")?.value?.trim() || ""' in source
    assert "fileHistorySearch()" in source
    assert "function fileHistoryRefreshList()" in source
    assert "refreshHistoryList = function" not in source
    assert "Legacy" not in source


def test_history_and_recovery_are_not_implemented_in_frontend_root() -> None:
    app = (WEB / "app.js").read_text(encoding="utf-8")
    source = (WEB / "file_history.js").read_text(encoding="utf-8")
    meeting = (WEB / "meeting.js").read_text(encoding="utf-8")

    for legacy_owner in (
        "function renderHistory(",
        "function loadHistorySession(",
        "function deleteSelectedHistory(",
        "function refreshHistoryList(",
        "function renderRecovery(",
        "function refreshRecovery(",
        'case "history_changed"',
        'case "recovery_audio_saved"',
    ):
        assert legacy_owner not in app

    assert 'name === "history_changed"' in source
    assert 'name === "recovery_audio_saved"' in source
    assert 'name === "meeting_completed"' in source
    assert "UltraUI.notify(\"historySession\", session)" in source
    assert "UltraUI.notify(\"historyClear\")" in source
    assert "refreshHistory()" not in meeting
    assert "historyIsVisible()" not in meeting


def test_live_recording_can_be_reopened_and_deleted_from_history() -> None:
    source = (WEB / "file_history.js").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")
    assert "getSessionRecordingInfo" in source
    assert "deleteSessionRecording" in source
    assert "def getSessionRecordingInfo" in bridge
    assert "def deleteSessionRecording" in bridge
    assert "session_recording_info" in application
    assert "delete_session_recording" in application
    assert "la trascrizione è stata conservata" in source


def test_postprocessing_never_replaces_raw_history_text() -> None:
    history = (ROOT / "core" / "transcript_history.py").read_text(encoding="utf-8")
    postprocess = (ROOT / "core" / "history_postprocess.py").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    assert "derived_outputs" in history
    assert "save_derived_output" in history
    assert "save_derived_output(session_id, profile, derived)" in postprocess
    assert "replace_text(session_id, derived)" not in postprocess
    assert "save_derived_output(" not in bridge
