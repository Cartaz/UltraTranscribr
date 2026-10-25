"""Settings drafts, nonblocking writes and model inventory."""

from dataclasses import asdict

from PySide6.QtCore import Property, Signal, Slot

from ui.adapters.base import Adapter
from ui.models import RecordModel

SECTIONS = {
    "recognition": ("model_size", "language", "audio_source", "vad_filter"),
    "history": ("history_retention_days", "meeting_audio_retention_days"),
    "dictation": ("dictation_activation_mode", "dictation_insertion_mode"),
    "audio": ("chunk_ms", "channels", "sink_name", "sink_search_keyword"),
    "tuning": ("beam_size", "vad_min_silence_ms", "buffer_warn_threshold"),
    "backend": (
        "server_port",
        "gpu_layers",
        "compute_type",
        "backend_instances",
        "preload_model",
    ),
}


class SettingsAdapter(Adapter):
    changed = Signal()

    def __init__(self, application, feedback, parent=None):
        super().__init__(application, feedback, parent)
        self.models = RecordModel(parent=self)
        self._values = {}
        self._draft = {}
        self._model_busy = ""
        self._writing = False

    @Property("QVariantMap", notify=changed)
    def values(self):
        return {**self._values, **self._draft}

    @Property(str, notify=changed)
    def modelBusy(self):
        return self._model_busy

    @Property(bool, notify=changed)
    def saving(self):
        return self._writing

    def hydrate(self, values):
        self._values = dict(values)
        self.changed.emit()

    @Slot(str, "QVariant")
    def edit(self, key, value):
        if key in set().union(*SECTIONS.values()):
            self._draft[key] = value

    def _write(self, overrides, captured, message):
        if self._writing:
            self.feedback.show("Salvataggio già in corso")
            return
        self._writing = True
        self.changed.emit()

        def finish():
            self._writing = False
            self.changed.emit()

        def receive(value):
            try:
                for key in overrides:
                    if key in captured and self._draft.get(key) == captured[key]:
                        self._draft.pop(key, None)
                self.hydrate(asdict(value))
                self.feedback.show(message)
            finally:
                finish()

        self.background(
            "qml-settings-save",
            lambda: self.application.apply_settings(overrides),
            receive,
            finish,
        )

    @Slot()
    def save(self):
        captured = dict(self._draft)
        overrides = dict(captured)
        try:
            if "channels" in overrides:
                overrides["channels"] = int(overrides["channels"])
            if overrides.get("sink_name") == "":
                overrides["sink_name"] = None
        except (ValueError, TypeError) as exc:
            self.feedback.show(exc)
            return
        self._write(overrides, captured, "Impostazioni salvate")

    @Slot(str)
    def selectModel(self, model):
        self._write(
            {"model_size": model}, dict(self._draft), "Modello predefinito aggiornato"
        )

    @Slot(str)
    def reset(self, section):
        if section in SECTIONS:
            defaults = self.application.settings_defaults()
            self._write(
                {k: defaults[k] for k in SECTIONS[section]},
                dict(self._draft),
                "Sezione ripristinata",
            )

    @Slot()
    def refreshModels(self):
        self.background(
            "qml-model-inventory", self.application.list_models, self.models.replace
        )

    @Slot(str, bool)
    def manageModel(self, model, delete):
        if self._model_busy:
            self.feedback.show("Operazione sui modelli già in corso")
            return

        def start():
            (
                self.application.delete_model
                if delete
                else self.application.download_model
            )(model)
            self._model_busy = model
            self.changed.emit()

        self.attempt(start)

    def handle_event(self, name, value):
        if name == "config_changed":
            self._values.update(value or {})
        elif name in {"model_download_started", "model_download_progress"}:
            self._model_busy = str(value.get("model", ""))
            for i, row in enumerate(self.models.rows()):
                if row.get("model") == self._model_busy:
                    self.models.update(i, progress=value.get("percent") or 0)
        elif name in {
            "model_status_changed",
            "model_download_error",
            "model_delete_error",
        }:
            self._model_busy = ""
            self.refreshModels()
        self.changed.emit()
