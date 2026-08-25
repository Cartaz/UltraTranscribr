"use strict";

const settingSections = {
  recognition: ["model_size", "language", "audio_source", "vad_filter"],
  history: ["history_retention_days", "meeting_audio_retention_days"],
  tuning: ["beam_size", "vad_min_silence_ms", "buffer_warn_threshold"],
  audio: ["chunk_ms", "channels", "sink_name", "sink_search_keyword"],
  backend: ["server_port", "gpu_layers", "compute_type", "backend_instances", "preload_model"],
};

let settingsDefaults = null;

function settingsEnsureUI() {
  const backendCard = [...document.querySelectorAll('[data-settings-pane="advanced"] .card')]
    .find(card => card.querySelector('input[name="server_port"]'));
  if (backendCard && !document.querySelector('[name="backend_instances"]')) {
    const fields = backendCard.querySelector('.fields');
    fields?.insertAdjacentHTML('beforeend', `
      <div><label for="s-instances">Istanze backend</label><input id="s-instances" name="backend_instances" type="number" min="1" max="4"></div>
      <div><label class="toggle-row compact-toggle" for="s-preload"><span><strong>Preload all'avvio</strong><small>Carica il modello installato all'apertura.</small></span><input id="s-preload" name="preload_model" type="checkbox"><i></i></label></div>`);
  }
}

function settingElement(name) {
  return document.querySelector(`#settings-form [name="${name}"]`);
}

function writeSetting(name, value) {
  const element = settingElement(name);
  if (!element) return;
  if (element.type === "checkbox") element.checked = !!value;
  else element.value = value == null ? "" : String(value);
}

function hydrateSettings(settings) {
  if (!settings || typeof settings !== "object") return;
  Object.entries(settings).forEach(([name, value]) => writeSetting(name, value));
}

function switchSettingsTab(name) {
  const target = name === "advanced" ? "advanced" : "normal";
  all("[data-settings-tab]").forEach(button => {
    const active = button.dataset.settingsTab === target;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  all("[data-settings-pane]").forEach(pane => {
    pane.hidden = pane.dataset.settingsPane !== target;
  });
}

function applySettingsPayload(payload, successMessage) {
  call("applySettings", [JSON.stringify(payload)], result => {
    const response = json(result);
    if (!response?.ok) {
      showError(response?.error || "Impostazioni non applicate", "settings");
      return;
    }
    state.boot.settings = response.settings;
    hydrateSettings(response.settings);
    state.source = normalizeSource(response.settings.audio_source);
    sourceUI();
    refreshDevices();
    updateFileSummary();
    notice(successMessage);
  });
}

function loadSettingsDefaults(callback) {
  if (settingsDefaults) {
    callback(settingsDefaults);
    return;
  }
  call("getSettingsDefaults", [], result => {
    const defaults = json(result);
    if (!defaults || typeof defaults !== "object") {
      showError("Impossibile leggere i valori predefiniti", "settings");
      return;
    }
    settingsDefaults = defaults;
    callback(defaults);
  });
}

function resetSettingsSection(sectionName) {
  if (sessionBusy() || state.modelBusy) {
    notice("Ferma le operazioni attive prima di ripristinare questa sezione", true);
    return;
  }
  const keys = settingSections[sectionName];
  if (!keys) return;
  loadSettingsDefaults(defaults => {
    const payload = {};
    keys.forEach(key => { payload[key] = defaults[key]; });
    applySettingsPayload(payload, "Sezione ripristinata ai valori predefiniti");
  });
}

const settingsModule = {
  bind() {
    settingsEnsureUI();
    all("[data-settings-tab]").forEach(button => {
      button.onclick = () => switchSettingsTab(button.dataset.settingsTab);
    });
    all("[data-reset-section]").forEach(button => {
      button.onclick = () => resetSettingsSection(button.dataset.resetSection);
    });
  },
  hydrate(bootstrap) {
    settingsEnsureUI();
    hydrateSettings(bootstrap.settings || {});
    switchSettingsTab("normal");
    lockSettings();
  },
  lockSettings() {
    const disabled = sessionBusy() || !!state.modelBusy;
    all(".settings-reset").forEach(button => { button.disabled = disabled; });
  },
  saveSettings(eventObject) {
    eventObject.preventDefault();
    const payload = {};
    for (const element of eventObject.currentTarget.elements) {
      if (!element.name || element.disabled) continue;
      if (element.name === "window_width" || element.name === "window_height") continue;
      if (element.type === "checkbox") payload[element.name] = element.checked;
      else if (element.type === "number") payload[element.name] = Number(element.value);
      else payload[element.name] = element.value === "" && element.name === "sink_name" ? null : element.value;
    }
    applySettingsPayload(payload, "Impostazioni salvate");
    return true;
  },
};

UltraUI.register(settingsModule);
settingsEnsureUI();

function loadStyle(href, marker) {
  if (document.querySelector(`link[data-ultra-module="${marker}"]`)) return;
  const style = document.createElement("link");
  style.rel = "stylesheet";
  style.href = href;
  style.dataset.ultraModule = marker;
  document.head.append(style);
}

function loadScript(src, marker) {
  if (document.querySelector(`script[data-ultra-module="${marker}"]`)) return;
  const script = document.createElement("script");
  script.src = src;
  script.async = false;
  script.dataset.ultraModule = marker;
  document.head.append(script);
}

(function loadDomainModules() {
  loadStyle("file_history.css", "file-history");
  loadStyle("meeting.css", "meeting");
  loadScript("file_history.js", "file-history");
  loadScript("meeting.js", "meeting");
})();
