from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def read(path): return (ROOT / path).read_text(encoding="utf-8")

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

def test_close_hides_to_tray_instead_of_quitting():
    source = read("ui/main_window.py")
    assert "self.hide()" in source
    assert "event.ignore()" in source

def test_bridge_does_not_expose_generic_keyboard_injection():
    bridge = (ROOT.parent / "does-not-exist")
    injector = read("ui/native/text_injector.py")
    assert "paste_shortcut" in injector
    assert "send_key" not in injector
