from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_main_is_only_native_wiring_for_dictation():
    source = read("main.py")
    assert "DictationNativeIntegration" in source
    assert "DictationService(" not in source
    assert "transcribe_audio(" not in source


def test_controller_owns_dictation_and_priority_policy():
    source = read("core/app_controller.py")
    assert "DictationService(" in source
    assert "InferencePriority.BATCH" in source
    assert "InferencePriority.INTERACTIVE" in source
    dictation = read("core/dictation_session.py")
    assert "InferencePriority" not in dictation


def test_native_dictation_uses_application_boundary():
    native = read("ui/native/dictation_integration.py")
    application = read("core/application_service.py")
    main = read("main.py")

    assert "ApplicationService" in native
    assert "AppController" not in native
    assert ".controller" not in native
    assert "DictationNativeIntegration(application, app)" in main

    for method in (
        "dictation_insertion_mode",
        "dictation_shortcut_pressed",
        "dictation_shortcut_released",
        "dictation_text_inserted",
    ):
        assert f"def {method}" in application


def test_close_hides_to_tray_instead_of_quitting():
    source = read("ui/main_window.py")
    assert "self.hide()" in source
    assert "event.ignore()" in source


def test_bridge_does_not_expose_generic_keyboard_injection():
    injector = read("ui/native/text_injector.py")
    assert "paste_shortcut" in injector
    assert "send_key" not in injector
