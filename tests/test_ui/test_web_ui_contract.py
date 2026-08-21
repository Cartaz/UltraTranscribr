"""Static contract tests for the embedded dark-neumorphic web UI."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "ui" / "web"


def test_web_ui_files_and_native_stack_are_present() -> None:
    expected = [
        ROOT / "ui" / "__init__.py",
        ROOT / "ui" / "bridge.py",
        ROOT / "ui" / "main_window.py",
        ROOT / "ui" / "tray_icon.py",
        WEB / "index.html",
        WEB / "styles.css",
        WEB / "history.css",
        WEB / "models.css",
        WEB / "runtime.css",
        WEB / "app.js",
    ]
    for path in expected:
        assert path.is_file(), f"missing UI file: {path.relative_to(ROOT)}"

    main_window = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "QWebEngineView" in main_window
    assert "QWebChannel" in main_window


def test_dark_neumorphism_uses_exact_surface_and_accent_without_gradients() -> None:
    css = (WEB / "styles.css").read_text(encoding="utf-8").lower()
    history_css = (WEB / "history.css").read_text(encoding="utf-8").lower()
    models_css = (WEB / "models.css").read_text(encoding="utf-8").lower()
    runtime_css = (WEB / "runtime.css").read_text(encoding="utf-8").lower()
    assert "--surface: rgb(20, 20, 20)" in css
    assert "--accent: rgb(255, 102, 0)" in css
    assert "box-shadow" in css
    assert "inset" in css
    assert "gradient(" not in css
    assert "gradient(" not in history_css
    assert "gradient(" not in models_css
    assert "gradient(" not in runtime_css


def test_frontend_is_wired_to_real_backend_operations() -> None:
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")

    for operation in (
        "start_transcription",
        "stop_transcription",
        "stop_listening",
        "start_file_transcription",
        "stop_file_transcription",
        "update_settings",
    ):
        assert operation in bridge

    for event in (
        "transcriber_buffer_level",
        "transcriber_new_text",
        "file_transcriber_progress",
        "file_transcriber_full_text",
    ):
        assert event in bridge
        assert event in script

    assert "setInterval(" not in script
    assert "Math.random(" not in script


def test_navigation_and_accessibility_contract() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    for panel in ("live", "file", "history", "settings", "logs"):
        assert f'data-panel="{panel}"' in html
        assert f'data-view="{panel}"' in html

    assert 'aria-live="polite"' in html
    assert 'role="progressbar"' in html
    assert "aria-current" in script
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css


def test_compact_layout_has_no_page_scroll_or_redundant_session_settings() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    for element_id in ("live-language", "live-model", "file-language", "file-model", "title", "subtitle"):
        assert f'id="{element_id}"' not in html

    assert 'class="chip"' not in html
    assert '[hidden] { display: none !important; }' in css
    assert 'html, body { margin: 0; width: 100%; height: 100%; overflow: hidden;' in css
    assert 'const allowedModelChoices = ["large-v3", "large-v3-turbo", "medium"]' in script
    assert 'settings.language || "auto"' in script
    assert 'settings.model_size || "large-v3-turbo"' in script


def test_history_and_recovery_are_backed_by_python_persistence() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    controller = (ROOT / "core" / "app_controller.py").read_text(encoding="utf-8")
    transcriber = (ROOT / "core" / "transcriber.py").read_text(encoding="utf-8")

    for element_id in ("history-list", "recovery-list", "history-export", "history-delete", "s-retention"):
        assert f'id="{element_id}"' in html

    for operation in (
        "listHistory", "getHistorySession", "exportHistorySession",
        "deleteHistorySession", "listRecoveryAudio", "startRecovery", "deleteRecovery",
    ):
        assert operation in bridge
        assert operation in script

    assert "TranscriptHistoryStore" in controller
    assert "transcriber_new_text" in controller
    assert "history_retention_days" in controller
    assert 'EventBus().emit("recovery_audio_saved"' in transcriber
    assert "refreshHistory" in script


def test_model_manager_uses_real_backend_inventory_and_progress() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    controller = (ROOT / "core" / "app_controller.py").read_text(encoding="utf-8")
    manager = (ROOT / "core" / "whisper_models.py").read_text(encoding="utf-8")

    assert 'id="model-list"' in html
    assert 'id="models-refresh"' in html
    assert 'href="models.css"' in html
    for operation in ("listModels", "downloadModel", "deleteModel"):
        assert operation in bridge and operation in script
    for event in ("model_download_started", "model_download_progress", "model_status_changed"):
        assert event in bridge and event in controller and event in script
    assert "list_ui_models" in manager
    assert "download_model" in manager
    assert "delete_model" in manager
    assert '"large-v3", "large-v3-turbo", "medium"' in manager


def test_runtime_status_is_explicit_and_session_summaries_are_read_only() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")
    controller = (ROOT / "core" / "app_controller.py").read_text(encoding="utf-8")
    runtime_css = (WEB / "runtime.css").read_text(encoding="utf-8")

    for element_id in (
        "live-device-value", "live-model-value", "live-language-value",
        "file-model-value", "file-language-value", "file-name-value",
    ):
        assert f'id="{element_id}"' in html

    for status in (
        "preparing_vad", "configuring_backend", "downloading_model",
        "loading_model", "starting_backend", "ready", "standby", "error",
    ):
        assert status in script and status in controller

    assert "friendlyError" in script
    assert "Audio di sistema non rilevato" in script
    assert "whisper-server non si è avviato correttamente" in script
    assert "session-summary" in runtime_css
    assert 'href="runtime.css"' in html


def test_live_ui_uses_generic_system_application_and_microphone_sources() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")
    settings = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
    finder = (ROOT / "core" / "sink_finder.py").read_text(encoding="utf-8")

    for source in ("system", "application", "microphone"):
        assert f'data-source="{source}"' in html
        assert f'<option value="{source}">' in html
    assert 'data-source="firefox"' not in html
    assert '<option value="firefox">' not in html
    assert 'source: "system"' in script
    assert 'APPLICATION = "application"' in settings
    assert 'SYSTEM = "system"' in settings
    assert "find_system_monitor" in finder


def test_application_stream_ui_uses_real_routing_backend() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")
    controller = (ROOT / "core" / "app_controller.py").read_text(encoding="utf-8")
    routing = (ROOT / "core" / "audio_routing.py").read_text(encoding="utf-8")
    runtime_css = (WEB / "runtime.css").read_text(encoding="utf-8")

    for element_id in ("live-stream", "live-stream-meta", "stream-refresh"):
        assert f'id="{element_id}"' in html

    assert "listPlaybackStreams" in bridge
    assert "listPlaybackStreams" in script
    assert "playback_stream_status_changed" in bridge
    assert "playback_stream_status_changed" in controller
    assert "playback_stream_status_changed" in script
    assert "PulseAudioRouter" in controller
    assert "module-null-sink" in routing
    assert "move-sink-input" in routing
    assert "cleanup_stale_routes" in routing
    assert "ambiguous" in routing
    assert "reconnected" in routing
    assert "grid-template-columns: repeat(3" in runtime_css
