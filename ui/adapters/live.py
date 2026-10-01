"""Incremental session models and Live commands."""

from PySide6.QtCore import Property, Signal, Slot
from ui.adapters.base import Adapter
from ui.models import RecordModel


class LiveAdapter(Adapter):
    changed = Signal()

    def __init__(self, application, feedback, sources, parent=None):
        super().__init__(application, feedback, parent)
        self.sources = sources
        self.sessions = RecordModel(parent=self)
        self.groups = RecordModel(parent=self)
        self.changed.connect(self._sync_groups)

    def _sync_groups(self):
        rows = self.sessions.rows()
        groups = [
            {
                "id": str(i // 2),
                "left": rows[i],
                "right": rows[i + 1] if i + 1 < len(rows) else {},
            }
            for i in range(0, len(rows), 2)
        ]
        for row in groups:
            self.groups.upsert(row)
        while self.groups.count > len(groups):
            self.groups.remove(self.groups.count - 1)

    @Property(int, notify=changed)
    def activeCount(self):
        return sum(not r.get("terminal", False) for r in self.sessions.rows())

    def hydrate(self, rows):
        self.sessions.replace(rows)
        self.changed.emit()

    @Slot(bool)
    def start(self, record=False):
        self.attempt(
            lambda: self.application.start_live(
                self.sources.source, self.sources.selected, "", record
            )
        )

    @Slot(str, bool)
    def stop(self, session_id, drain):
        self.attempt(lambda: self.application.stop_live(session_id, drain=drain))

    @Slot(bool)
    def stopAll(self, drain):
        self.attempt(lambda: self.application.stop_all_live(drain=drain))

    @Slot(str)
    def remove(self, session_id):
        self.attempt(lambda: self.application.remove_live(session_id))

    @Slot(str)
    def copy(self, session_id):
        for row in self.sessions.rows():
            if row.get("id") == session_id:
                self.feedback.copy(row.get("text") or "")
                break

    def handle_event(self, name, value):
        if not isinstance(value, dict):
            return
        session_id = value.get("id") or value.get("session_id")
        if name == "live_session_removed":
            self.sessions.remove_key(session_id)
        elif value.get("id"):
            self.sessions.upsert(value)
        else:
            for i, row in enumerate(self.sessions.rows()):
                if row.get("id") != session_id:
                    continue
                if name == "live_session_text":
                    self.sessions.update(
                        i,
                        text=(
                            str(row.get("text") or "")
                            + "\n"
                            + str(value.get("text") or "")
                        ).strip(),
                    )
                elif name == "live_session_buffer_level":
                    self.sessions.update(i, buffer_level=value.get("level", 0))
                elif name == "live_session_queue_wait":
                    self.sessions.update(
                        i,
                        queue_wait_ms=value.get("wait_ms", 0),
                        queue_peak_ms=value.get("peak_ms", 0),
                    )
                elif name == "live_session_route_status":
                    self.sessions.update(
                        i,
                        route_status=value.get("status", ""),
                        source_path=(value.get("stream") or {}).get("display_name")
                        or row.get("source_path", ""),
                    )
                    if value.get("status") in {
                        "disconnected",
                        "ambiguous",
                        "reconnected",
                    }:
                        self.feedback.show(
                            "Routing "
                            + str(value.get("status"))
                            + ": "
                            + str(row.get("source_path") or session_id)
                        )
                break
        self.changed.emit()
