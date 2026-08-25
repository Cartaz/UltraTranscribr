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

function settingsFormatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KiB`;
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MiB`;
  return `${(bytes / 1073741824).toFixed(2)} GiB`;
}

function settingsModelDetail(item) {
  if (item.installed) return `${settingsFormatBytes(item.size_bytes)}${item.verified ? " · hash registrato" : ""}`;
  if (Number(item.partial_bytes) > 0) return `Parziale: ${settingsFormatBytes(item.partial_bytes)}`;
  return `Minimo atteso: ${settingsFormatBytes(item.min_bytes)}`;
}

function settingsRenderModels(items) {
  const list = $("model-list");
  if (!list) return;
  list.replaceChildren();
  if (!Array.isArray(items) || !items.length) {
    const empty = document.createElement("p");
    empty.className = "model-empty";
    empty.textContent = "Nessun modello disponibile.";
    list.append(empty);
    return;
  }
  items.forEach(item => {
    const row = document.createElement("div");
    row.className = "model-row";
    row.dataset.model = item.model;
    const main = document.createElement("div");
    main.className = "model-main";
    const title = document.createElement("strong");
    title.textContent = modelLabels[item.model] || item.model;
    const detail = document.createElement("small");
    detail.textContent = settingsModelDetail(item);
    main.append(title, detail);

    const progressWrap = document.createElement("div");
    progressWrap.className = "model-progress-wrap";
    const statusLine = document.createElement("div");
    statusLine.className = "model-status-line";
    const orb = document.createElement("span");
    orb.className = "orb" + (item.installed ? " active" : "");
    const stateLabel = document.createElement("span");
    stateLabel.className = "model-state" + (item.installed ? " installed" : "");
    const active = state.modelBusy === item.model;
    stateLabel.textContent = active ? "Operazione in corso" : item.installed ? "Installato" : "Non installato";
    statusLine.append(orb, stateLabel);

    const bar = document.createElement("div");
    bar.className = "progress";
    bar.setAttribute("role", "progressbar");
    bar.setAttribute("aria-valuemin", "0");
    bar.setAttribute("aria-valuemax", "100");
    const progressState = state.modelProgress[item.model] || null;
    const percent = progressState?.percent == null ? 0 : Math.max(0, Math.min(100, Number(progressState.percent)));
    const fill = document.createElement("span");
    fill.style.width = `${percent}%`;
    bar.setAttribute("aria-valuenow", String(percent));
    bar.append(fill);
    const progressLabel = document.createElement("div");
    progressLabel.className = "model-progress-label";
    if (active && progressState) {
      progressLabel.textContent = progressState.total
        ? `${settingsFormatBytes(progressState.downloaded)} / ${settingsFormatBytes(progressState.total)} · ${percent}%`
        : `${settingsFormatBytes(progressState.downloaded)} scaricati`;
    } else if (!item.installed && Number(item.partial_bytes) > 0) {
      progressLabel.textContent = `Download riprendibile da ${settingsFormatBytes(item.partial_bytes)}`;
    } else {
      progressLabel.textContent = item.installed ? "Pronto all'uso" : "Non scaricato";
    }
    progressWrap.append(statusLine, bar, progressLabel);

    const actions = document.createElement("div");
    actions.className = "model-actions";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button" + (!item.installed ? " selected" : "");
    button.textContent = active ? "Attendi…" : item.installed ? "Elimina" : Number(item.partial_bytes) > 0 ? "Riprendi" : "Scarica";
    button.disabled = sessionBusy() || !!state.modelBusy;
    button.onclick = () => item.installed ? settingsRequestDeleteModel(item.model) : settingsRequestDownloadModel(item.model);
    actions.append(button);
    row.append(main, progressWrap, actions);
    list.append(row);
  });
}

function settingsRefreshModels() {
  call("listModels", [], result => {
    const models = json(result);
    state.models = Array.isArray(models) ? models : [];
    settingsRenderModels(state.models);
  });
}

function settingsRequestDownloadModel(model) {
  if (sessionBusy() || state.modelBusy) return;
  state.modelBusy = model;
  state.modelProgress[model] = {downloaded: 0, total: null, percent: 0};
  settingsRenderModels(state.models);
  lockSettings();
  call("downloadModel", [model], result => {
    const response = json(result);
    if (!response?.ok) {
      state.modelBusy = null;
      state.modelProgress = {};
      settingsRenderModels(state.models);
      lockSettings();
      showError(response?.error || "Download modello non avviato", "model");
    }
  });
}

function settingsRequestDeleteModel(model) {
  if (sessionBusy() || state.modelBusy) return;
  if (!window.confirm(`Eliminare ${modelLabels[model] || model} dal disco?`)) return;
  state.modelBusy = model;
  settingsRenderModels(state.models);
  lockSettings();
  call("deleteModel", [model], result => {
    const response = json(result);
    if (!response?.ok) {
      state.modelBusy = null;
      settingsRenderModels(state.models);
      lockSettings();
      showError(response?.error || "Eliminazione modello non avviata", "model");
    }
  });
}

function settingsUpdateModelProgress(payload) {
  if (!payload?.model) return;
  state.modelBusy = payload.model;
  state.modelProgress[payload.model] = {
    downloaded: Number(payload.downloaded) || 0,
    total: payload.total == null ? null : Number(payload.total),
    percent: payload.percent == null ? null : Number(payload.percent),
  };
  settingsRenderModels(state.models);
  lockSettings();
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
    settingsRenderModels(state.models);
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

function settingsSave(eventObject) {
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
    $("settings-form").onsubmit = settingsSave;
    $("models-refresh").onclick = settingsRefreshModels;
  },
  hydrate(bootstrap) {
    settingsEnsureUI();
    options($("s-model"), bootstrap.modelChoices || [], bootstrap.settings?.model_size || "");
    hydrateSettings(bootstrap.settings || {});
    state.models = Array.isArray(bootstrap.models) ? bootstrap.models : [];
    settingsRenderModels(state.models);
    switchSettingsTab("normal");
    lockSettings();
  },
  view(name) {
    if (name === "settings") settingsRefreshModels();
  },
  lockSettings() {
    const disabled = sessionBusy() || !!state.modelBusy;
    all(".settings-reset").forEach(button => { button.disabled = disabled; });
    settingsRenderModels(state.models);
  },
  event(name, value) {
    if (name === "config_changed" && value && typeof value === "object") {
      hydrateSettings({...state.boot?.settings, ...value});
      return false;
    }
    if (name === "model_download_started") {
      state.modelBusy = value?.model || null;
      if (state.modelBusy) state.modelProgress[state.modelBusy] = {downloaded: 0, total: null, percent: 0};
      settingsRenderModels(state.models);
      lockSettings();
      return true;
    }
    if (name === "model_download_progress") {
      settingsUpdateModelProgress(value);
      if (state.backendState === "downloading_model" && value?.model) {
        const pct = value.percent == null ? "" : ` · ${Math.max(0, Math.min(100, Number(value.percent) || 0))}%`;
        globalStatus(`Download ${modelLabels[value.model] || value.model}${pct}`, "working");
      }
      return true;
    }
    if (name === "model_status_changed") {
      state.modelBusy = null;
      state.modelProgress = {};
      lockSettings();
      settingsRefreshModels();
      return true;
    }
    if (name === "model_download_error" || name === "model_delete_error") {
      state.modelBusy = null;
      state.modelProgress = {};
      lockSettings();
      showError(value, "model");
      settingsRefreshModels();
      return true;
    }
    return false;
  },
};

UltraUI.register(settingsModule);
settingsEnsureUI();
