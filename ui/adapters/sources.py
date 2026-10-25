"""Audio discovery presentation, keeping selection stable across refreshes."""

from PySide6.QtCore import Property, Signal, Slot

from ui.adapters.base import Adapter
from ui.models import RecordModel


class SourcesAdapter(Adapter):
    changed = Signal()

    def __init__(self, application, feedback, parent=None):
        super().__init__(application, feedback, parent)
        self.devices = RecordModel(parent=self)
        self.microphones = RecordModel(parent=self)
        self.monitors = RecordModel(parent=self)
        self.streams = RecordModel(parent=self)
        self._all_devices = []
        self._source = "system"
        self._selected = ""
        self._health = {}

    @Property(str, notify=changed)
    def source(self):
        return self._source

    @Property(str, notify=changed)
    def selected(self):
        return self._selected

    @Property("QVariantMap", notify=changed)
    def health(self):
        return self._health

    @Slot(str)
    def setSource(self, source):
        if source not in {"system", "application", "microphone"}:
            self.feedback.show("Sorgente non valida")
            return
        self._source = source
        self._selected = ""
        self._populate()
        self.changed.emit()
        self.refresh()

    @Slot(str)
    def select(self, value):
        self._selected = value
        self.changed.emit()
        self.probe()

    def _populate(self):
        for model, key in ((self.microphones, "is_mic"), (self.monitors, "is_monitor")):
            model.replace(
                [{"name": "Rilevamento automatico", "value": ""}]
                + [{**d, "value": d["name"]} for d in self._all_devices if d.get(key)]
            )
        self.devices.replace(
            (self.monitors if self._source == "system" else self.microphones).rows()
        )

    def set_devices(self, rows):
        self._all_devices = rows or []
        self._populate()

    def set_streams(self, rows):
        self.streams.replace(
            [
                {
                    "name": "Seleziona uno stream"
                    if rows
                    else "Nessuno stream in riproduzione",
                    "value": "",
                }
            ]
            + [
                {
                    **r,
                    "name": r.get("display_name", str(r.get("id"))),
                    "value": str(r.get("id")),
                }
                for r in rows or []
            ]
        )

    def set_health(self, value):
        if (
            value.get("source") == self._source
            and str(value.get("selected_input", "")) == self._selected
        ):
            self._health = value
            self.changed.emit()

    @Slot()
    def refresh(self):
        self.attempt(lambda: self.application.refresh_devices(self._source))
        self.attempt(self.application.list_playback_streams)
        self.probe()

    @Slot()
    def probe(self):
        value = self.attempt(
            lambda: self.application.probe_audio_source(self._source, self._selected)
        )
        if value:
            self.set_health(value)
