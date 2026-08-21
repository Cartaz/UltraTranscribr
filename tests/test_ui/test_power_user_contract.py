from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_power_user_frontend_module_exists() -> None:
    assert (ROOT / "ui" / "web" / "power_user.js").is_file()
    assert (ROOT / "ui" / "web" / "power_user.css").is_file()


def test_power_user_module_exposes_batch_search_and_exports() -> None:
    source = (ROOT / "ui" / "web" / "power_user.js").read_text(encoding="utf-8")
    for token in (
        "chooseAudioFiles",
        "enqueueFileBatch",
        "file_drop_received",
        "searchHistory",
        'powerExport("srt")',
        'powerExport("vtt")',
        "generatePostprocess",
    ):
        assert token in source


def test_history_refresh_preserves_active_search_filter() -> None:
    source = (ROOT / "ui" / "web" / "power_user.js").read_text(encoding="utf-8")
    assert "powerLegacyRefreshHistoryList = refreshHistoryList" in source
    assert 'const query = $("history-search")?.value?.trim() || ""' in source
    assert "if (query) powerSearchHistory()" in source


def test_desktop_shell_captures_local_file_drops() -> None:
    source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "class DropAwareWebView" in source
    assert "filesDropped = Signal(list)" in source
    assert "event.acceptProposedAction()" in source
    assert "self._bridge.emitDroppedFiles" in source


def test_desktop_shell_closes_power_user_coordinator_before_controller_shutdown() -> None:
    source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "def _shutdown_runtime" in source
    assert source.count("self._bridge.closePowerUser()") == 1
    assert "finally:\n            self._controller.shutdown()" in source
    assert "self._bridge.cancelFileQueue()" in source
    assert "self._bridge.stopFile()" not in source


def test_bridge_exposes_power_user_operations() -> None:
    source = (ROOT / "ui" / "multi_session_bridge.py").read_text(encoding="utf-8")
    for method in (
        "def closePowerUser",
        "def chooseAudioFiles",
        "def enqueueFileBatch",
        "def searchHistory",
        "def generatePostprocess",
        "def exportHistoryFormat",
    ):
        assert method in source
    assert 'fmt not in {"txt", "srt", "vtt"}' in source


def test_postprocessing_never_replaces_raw_history_text() -> None:
    history = (ROOT / "core" / "transcript_history.py").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "multi_session_bridge.py").read_text(encoding="utf-8")
    assert "derived_outputs" in history
    assert "save_derived_output" in history
    assert "save_derived_output(session_id, profile, derived)" in bridge
    assert "replace_text(session_id, derived)" not in bridge


def test_timestamped_file_events_are_persisted() -> None:
    worker = (ROOT / "core" / "file_transcriber.py").read_text(encoding="utf-8")
    journal = (ROOT / "core" / "file_segment_journal.py").read_text(encoding="utf-8")
    assert 'bus.emit("file_transcriber_segments", segments)' in worker
    assert "append_segments(session_id, payload)" in journal
