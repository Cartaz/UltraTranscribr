"use strict";

const phase6SettingSections = {
  recognition: ["model_size", "language", "audio_source", "vad_filter"],
  history: ["history_retention_days"],
  tuning: ["beam_size", "vad_min_silence_ms", "buffer_warn_threshold"],
  audio: ["chunk_ms", "channels", "sink_name", "sink_search_keyword"],
  backend: ["server_port", "gpu_layers", "compute_type"],
};

let phase6SettingsDefaults = null;

function phase6SettingElement(name) {
  return document.querySelector(`#settings-form [name="${name}"]`);
}

function phase6WriteSetting(name, value) {
  const element = phase6SettingElement(name);
  if (!element) return;
  if (element.type === "checkbox") element.checked = !!value;
  else element.value = value == null ? "" : String(value);
}

function phase6HydrateSettings(settings) {
  if (!settings || typeof settings !== "object") return;
  Object.entries(settings).forEach(([name, value]) => phase6WriteSetting(name, value));
}

function phase6SwitchSettingsTab(name) {
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

function phase6ApplySettings(payload, successMessage) {
  call("applySettings", [JSON.stringify(payload)], result => {
    const response = json(result);
    if (!response?.ok) {
      showError(response?.error || "Impostazioni non applicate", "settings");
      return;
    }
    state.boot.settings = response.settings;
    phase6HydrateSettings(response.settings);
    state.source = normalizeSource(response.settings.audio_source);
    sourceUI();
    refreshDevices();
    updateFileSummary();
    notice(successMessage);
  });
}

function phase6LoadDefaults(callback) {
  if (phase6SettingsDefaults) {
    callback(phase6SettingsDefaults);
    return;
  }
  call("getSettingsDefaults", [], result => {
    const defaults = json(result);
    if (!defaults || typeof defaults !== "object") {
      showError("Impossibile leggere i valori predefiniti", "settings");
      return;
    }
    phase6SettingsDefaults = defaults;
    callback(defaults);
  });
}

function resetSettingsSection(sectionName) {
  if (sessionBusy() || state.modelBusy) {
    notice("Ferma le operazioni attive prima di ripristinare questa sezione", true);
    return;
  }
  const keys = phase6SettingSections[sectionName];
  if (!keys) return;
  phase6LoadDefaults(defaults => {
    const payload = {};
    keys.forEach(key => { payload[key] = defaults[key]; });
    phase6ApplySettings(payload, "Sezione ripristinata ai valori predefiniti");
  });
}

const phase6LegacyLockSettings = lockSettings;
lockSettings = function() {
  phase6LegacyLockSettings();
  const disabled = sessionBusy() || !!state.modelBusy;
  all(".settings-reset").forEach(button => { button.disabled = disabled; });
};

saveSettings = function(eventObject) {
  eventObject.preventDefault();
  const payload = {};
  for (const element of eventObject.currentTarget.elements) {
    if (!element.name || element.disabled) continue;
    if (element.name === "window_width" || element.name === "window_height") continue;
    if (element.type === "checkbox") payload[element.name] = element.checked;
    else if (element.type === "number") payload[element.name] = Number(element.value);
    else payload[element.name] = element.value === "" && element.name === "sink_name" ? null : element.value;
  }
  phase6ApplySettings(payload, "Impostazioni salvate");
};

const phase6LegacyHydrate = hydrate;
hydrate = function(bootstrap) {
  phase6LegacyHydrate(bootstrap);
  phase6HydrateSettings(bootstrap.settings || {});
  phase6SwitchSettingsTab("normal");
  lockSettings();
};

const phase6LegacyBind = bind;
bind = function() {
  phase6LegacyBind();
  all("[data-settings-tab]").forEach(button => {
    button.onclick = () => phase6SwitchSettingsTab(button.dataset.settingsTab);
  });
  all("[data-reset-section]").forEach(button => {
    button.onclick = () => resetSettingsSection(button.dataset.resetSection);
  });
};

(function loadPowerUserModule() {
  if (!document.querySelector('link[data-ultra-power="1"]')) {
    const style = document.createElement("link");
    style.rel = "stylesheet";
    style.href = "power_user.css";
    style.dataset.ultraPower = "1";
    document.head.append(style);
  }
  if (!document.querySelector('script[data-ultra-power="1"]')) {
    const script = document.createElement("script");
    script.src = "power_user.js";
    script.dataset.ultraPower = "1";
    document.head.append(script);
  }
})();
