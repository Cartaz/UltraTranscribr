"""Real Qt Quick shell replaces the browser smoke test."""

from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest
from conftest import wait_until


def test_real_main_window_constructs_local_qml_shell(quick_window):
    app, window, service, controller, messages = quick_window
    root = window._window
    assert (root.minimumWidth(), root.minimumHeight()) == (1200, 800)
    assert window._engine.rootObjects() == [root]
    button = root.findChild(QObject, "navFile")
    QTest.mouseClick(
        root,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint(),
    )
    wait_until(lambda: root.property("view") == "file")
    for view in ("live", "file", "meeting", "history", "settings", "logs"):
        root.setProperty("view", view)
        app.processEvents()
    assert not any(
        any(
            error in m
            for error in (
                "TypeError",
                "ReferenceError",
                "Binding loop",
                "recursive rearrange",
            )
        )
        for m in messages
    ), messages
    window.dispose()
    window.dispose()
    assert not window.runtime._handlers
    assert service.desktop_state()["window_width"] == 1200
    assert service.desktop_state()["window_height"] == 800
