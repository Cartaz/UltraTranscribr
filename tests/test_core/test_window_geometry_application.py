from config.settings import Settings
from core.application_service import ApplicationService


class _History:
    def migrate_legacy_session_names(self) -> None:
        return None


class _Controller:
    def __init__(self) -> None:
        self.file_batch = object()
        self.meeting = object()
        self.history = _History()
        self.settings = Settings(
            window_x=-100,
            window_y=30,
            window_width=1300,
            window_height=820,
        )
        self.updates: list[dict[str, object]] = []

    def active_live_count(self) -> int:
        return 0

    def update_settings(self, **overrides: object) -> None:
        self.updates.append(dict(overrides))
        self.settings = self.settings.with_(**overrides)


def test_desktop_state_exposes_complete_geometry() -> None:
    controller = _Controller()
    service = ApplicationService(controller)  # type: ignore[arg-type]
    try:
        state = service.desktop_state()
    finally:
        service.close()

    assert state["window_x"] == -100
    assert state["window_y"] == 30
    assert state["window_width"] == 1300
    assert state["window_height"] == 820


def test_persist_window_geometry_updates_all_coordinates_atomically() -> None:
    controller = _Controller()
    service = ApplicationService(controller)  # type: ignore[arg-type]
    try:
        service.persist_window_geometry(210, 140, 1500, 900)
    finally:
        service.close()

    assert controller.updates == [
        {
            "window_x": 210,
            "window_y": 140,
            "window_width": 1500,
            "window_height": 900,
        }
    ]


def test_unchanged_geometry_does_not_rewrite_settings() -> None:
    controller = _Controller()
    service = ApplicationService(controller)  # type: ignore[arg-type]
    try:
        service.persist_window_geometry(-100, 30, 1300, 820)
    finally:
        service.close()

    assert controller.updates == []
