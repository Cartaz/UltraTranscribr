"use strict";

let backend = null;
const $ = id => document.getElementById(id);
const all = selector => [...document.querySelectorAll(selector)];

const state = {
  boot: null,
  source: "system",
  live: false,
  draining: false,
  file: false,
  liveText: "",
  fileText: "",
  historyText: "",
  historySelected: null,
  models: [],
  modelBusy: null,
  modelProgress: {},
  backendState: "standby",
  streams: [],
  selectedStreamId: null,
  routeStatus: "idle",
};

const uiModules = [];
const uiRuntime = {bound: false, bootstrap: null};

function registerUIModule(module) {
  if (!module || typeof module !== "object") return;
  uiModules.push(module);
  if (uiRuntime.bound && typeof module.bind === "function") module.bind();
  if (uiRuntime.bootstrap && typeof module.hydrate === "function") {
    module.hydrate(uiRuntime.bootstrap);
  }
}

function lastUIHandler(name) {
  return [...uiModules].reverse().find(module => typeof module[name] === "function") || null;
}

function notifyUIModules(name, ...args) {
  uiModules.forEach(module => module[name]?.(...args));
}

window.UltraUI = Object.freeze({register: registerUIModule, notify: notifyUIModules});

const views = {
  live: "TRASCRIZIONE LIVE",
  file: "TRASCRIZIONE FILE",
  history: "CRONOLOGIA",
  settings: "IMPOSTAZIONI",
  logs: "LOG E DIAGNOSTICA",
};
const allowedModelChoices = ["large-v3", "large-v3-turbo", "medium"];
const modelLabels = {
  "large-v3": "Large v3",
  "large-v3-turbo": "Large v3 Turbo",
  medium: "Medium",
};
const backendLabels = {
  standby: "Standby",
  preparing_vad: "Preparazione VAD",
  configuring_backend: "Configurazione backend",
  downloading_model: "Download modello",
  loading_model: "Caricamento modello",
  starting_backend: "Avvio backend",
  ready: "Pronto",
  error: "Errore",
};

function call(name, args = [], cb = null) {
  if (!backend || typeof backend[name] !== "function") return;
  if (cb) backend[name](...args, cb);
  else backend[name](...args);
}

function json(value) {
  try { return JSON.parse(value); }
  catch { return value; }
}

function notice(value, error = false) {
  $("notice-text").textContent = String(value || "");
  $("notice").hidden = false;
  $("notice").classList.toggle("error", error);
}

function switchView(name) {
  all(".nav").forEach(button => {
    const active = button.dataset.view === name;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  all(".view").forEach(panel => {
    const active = panel.dataset.panel === name;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  });
  $("eyebrow").textContent = views[name];
  if (name === "settings") refreshModels();
  uiModules.forEach(module => module.view?.(name));
}

function setOrb(id, on) { $(id).classList.toggle("active", !!on); }

function globalStatus(textValue, mode = "idle") {
  $("global-status").textContent = textValue;
  const orb = $("global-orb");
  orb.classList.remove("active", "working", "error");
  if (mode === "active") orb.classList.add("active");
  else if (mode === "working") orb.classList.add("working");
  else if (mode === "error") orb.classList.add("error");
}

function setBackendStatus(value) {
  const status = String(value || "standby");
  state.backendState = status;
  if (state.boot?.runtime) {
    if (status === "ready") state.boot.runtime.backendRunning = true;
    if (status === "standby" || status === "error") state.boot.runtime.backendRunning = false;
  }
  const mode = status === "ready" ? "active"
    : status === "error" ? "error"
      : status === "standby" ? "idle" : "working";
  globalStatus(backendLabels[status] || label(status), mode);
}

function restoreBackendStatus() {
  if (state.backendState === "error") setBackendStatus("error");
  else setBackendStatus(state.boot?.runtime?.backendRunning ? "ready" : "standby");
}

function progress(kind, value) {
  const n = Math.max(0, Math.min(100, Number(value) || 0));
  $(kind + "-fill").style.width = n + "%";
  $(kind + "-progress").setAttribute("aria-valuenow", String(n));
  $(kind === "buffer" ? "buffer-value" : "file-progress-value").textContent = Math.round(n) + "%";
}

function text(kind, value, full = false) {
  const key = kind + "Text";
  const box = $(kind + "-transcript");
  if (full) state[key] = String(value || "");
  else state[key] += (state[key] ? " " : "") + String(value || "");
  box.textContent = state[key] || "Il testo trascritto apparirà qui.";
  box.classList.toggle("placeholder", !state[key]);
  box.scrollTop = box.scrollHeight;
}

function sessionBusy() {
  return state.live || state.draining || state.file || uiModules.some(module => module.isBusy?.() === true);
}

function lockSettings() {
  $("settings-save").disabled = sessionBusy() || !!state.modelBusy;
  uiModules.forEach(module => module.lockSettings?.());
}

function liveUI(status) {
  const handler = uiModules.find(module => typeof module.liveUI === "function");
  if (handler) {
    handler.liveUI(status);
    return;
  }
  $("live-status").textContent = status;
  const busy = state.live || state.draining;
  const missingStream = state.source === "application" && !$("live-stream").value;
  $("live-start").disabled = busy || state.file || missingStream;
  $("live-stop").disabled = !busy;
  $("live-drain").disabled = !state.live || state.draining;
  setOrb("live-orb", busy);
  lockSettings();
  renderModels(state.models);
}

function fileUI(status) {
  $("file-status").textContent = status;
  $("file-start").disabled = sessionBusy();
  $("file-stop").disabled = !state.file;
  setOrb("file-orb", state.file);
  lockSettings();
  renderModels(state.models);
  uiModules.forEach(module => module.fileUI?.(status));
}

function options(select, values, current) {
  select.replaceChildren();
  values.forEach(value => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = modelLabels[value] || value;
    option.selected = value === current;
    select.append(option);
  });
}

function normalizeSource(source) {
  return ["system", "application", "microphone"].includes(source) ? source : "system";
}

function sourceLabel(source) {
  if (source === "microphone") return "Microfono";
  if (source === "application") return "Applicazione";
  return "Audio di sistema";
}

function devices(source, list) {
  const select = $("live-device");
  const current = select.value;
  select.innerHTML = '<option value="">Rilevamento automatico</option>';
  const key = source === "system" ? "is_monitor" : "is_mic";
  (list || []).filter(device => !!device[key]).forEach(device => {
    const option = document.createElement("option");
    option.value = device.name;
    option.textContent = device.name + (device.hostapi_name ? " · " + device.hostapi_name : "");
    select.append(option);
  });
  if ([...select.options].some(option => option.value === current)) select.value = current;
  updateLiveSummary();
}

function selectedDeviceLabel() {
  const select = $("live-device");
  if (!select.value) return "Automatico";
  return select.options[select.selectedIndex]?.textContent || select.value;
}

function streamMeta(stream) {
  if (!stream) return "Seleziona uno stream PipeWire/PulseAudio. Verrà isolato e ripristinato automaticamente al termine.";
  const pid = stream.process_id ? `PID ${stream.process_id}` : "PID —";
  const binary = stream.process_binary || "binario —";
  const sink = stream.sink_name || "sink —";
  const status = stream.state === "paused" ? "in pausa" : "in riproduzione";
  return `${pid} · ${binary} · ${sink} · ${status}`;
}

function selectedStream() {
  const id = Number($("live-stream").value);
  if (!Number.isFinite(id)) return null;
  return state.streams.find(stream => Number(stream.id) === id) || null;
}

function updateSelectedStreamMeta() {
  const stream = selectedStream();
  state.selectedStreamId = stream ? Number(stream.id) : null;
  $("live-stream-meta").textContent = streamMeta(stream);
  updateLiveSummary();
  liveUI($("live-status").textContent || "Idle");
  uiModules.forEach(module => module.streamMeta?.());
}

function renderPlaybackStreams(items) {
  const streams = Array.isArray(items) ? items : [];
  const select = $("live-stream");
  const previous = select.value || (state.selectedStreamId == null ? "" : String(state.selectedStreamId));
  state.streams = streams;
  select.replaceChildren();

  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = streams.length ? "Seleziona uno stream" : "Nessuno stream in riproduzione";
  select.append(placeholder);

  streams.forEach(stream => {
    const option = document.createElement("option");
    option.value = String(stream.id);
    const pid = stream.process_id ? `PID ${stream.process_id}` : "PID —";
    const stateText = stream.state === "paused" ? "pausa" : "playing";
    option.textContent = `${stream.display_name || `Stream #${stream.id}`} · ${pid} · ${stateText}`;
    option.title = `${stream.process_binary || ""} · ${stream.sink_name || ""}`;
    select.append(option);
  });

  if ([...select.options].some(option => option.value === previous)) select.value = previous;
  else select.value = "";
  updateSelectedStreamMeta();
}

function refreshStreams() {
  const handler = lastUIHandler("refreshStreams");
  if (handler && handler.refreshStreams() === true) return;
  call("listPlaybackStreams", [], result => {
    const response = json(result);
    if (Array.isArray(response)) {
      renderPlaybackStreams(response);
      return;
    }
    renderPlaybackStreams(response?.streams || []);
    if (response && response.ok === false) showError(response.error, "stream");
  });
}

function refreshDevices() {
  const handler = lastUIHandler("refreshDevices");
  if (handler && handler.refreshDevices() === true) return;
  if (state.source === "application") {
    refreshStreams();
    return;
  }
  call("refreshDevices", [state.source], result => devices(state.source, json(result)));
}

function selectedInputValue() {
  return state.source === "application" ? $("live-stream").value : $("live-device").value;
}

function selectedInputLabel() {
  if (state.source === "application") return selectedStream()?.display_name || "Nessuno stream";
  return selectedDeviceLabel();
}

function updateLiveSummary(runtime = null) {
  const settings = state.boot?.settings || {};
  const source = normalizeSource(runtime?.source || state.source || settings.audio_source || "system");
  $("live-source-value").textContent = sourceLabel(source);
  if (runtime?.stream) $("live-device-value").textContent = runtime.stream.display_name || `Stream #${runtime.stream.id}`;
  else if (source === "application") $("live-device-value").textContent = selectedInputLabel();
  else $("live-device-value").textContent = runtime?.sink || selectedDeviceLabel();
  $("live-model-value").textContent = modelLabels[settings.model_size] || settings.model_size || "—";
  $("live-language-value").textContent = settings.language || "auto";
}

function updateFileSummary(path = null) {
  const settings = state.boot?.settings || {};
  const sourcePath = path || $("file-path").value || "";
  $("file-model-value").textContent = modelLabels[settings.model_size] || settings.model_size || "—";
  $("file-language-value").textContent = settings.language || "auto";
  $("file-name-value").textContent = sourcePath ? fileName(sourcePath) : "—";
  $("file-name-value").title = sourcePath;
}

function sourceUI() {
  all(".segment").forEach(button => {
    const active = button.dataset.source === state.source;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  $("live-device-field").hidden = state.source === "application";
  $("live-stream-field").hidden = state.source !== "application";
  updateLiveSummary();
  liveUI($("live-status").textContent || "Idle");
  uiModules.forEach(module => module.sourceUI?.());
}

function hydrate(bootstrap) {
  uiRuntime.bootstrap = bootstrap;
  const moduleBootstrap = bootstrap;
  uiModules.forEach(module => {
    if (typeof module.transformBootstrap === "function") {
      bootstrap = module.transformBootstrap(bootstrap) || bootstrap;
    }
  });

  state.boot = bootstrap;
  state.models = Array.isArray(bootstrap.models) ? bootstrap.models : [];
  state.streams = Array.isArray(bootstrap.playbackStreams) ? bootstrap.playbackStreams : [];
  $("version").textContent = "v" + bootstrap.app.version;
  const selectedModel = allowedModelChoices.includes(bootstrap.settings.model_size)
    ? bootstrap.settings.model_size : "large-v3-turbo";
  options($("s-model"), allowedModelChoices, selectedModel);
  state.source = normalizeSource(bootstrap.settings.audio_source);
  devices(state.source === "application" ? "system" : state.source, bootstrap.devices);
  renderPlaybackStreams(state.streams);
  sourceUI();

  const map = {
    "s-language": "language",
    "s-source": "audio_source",
    "s-beam": "beam_size",
    "s-vad-silence": "vad_min_silence_ms",
    "s-buffer": "buffer_warn_threshold",
    "s-chunk": "chunk_ms",
    "s-channels": "channels",
    "s-sink": "sink_name",
    "s-keyword": "sink_search_keyword",
    "s-port": "server_port",
    "s-gpu": "gpu_layers",
    "s-compute": "compute_type",
    "s-width": "window_width",
    "s-height": "window_height",
    "s-retention": "history_retention_days",
  };
  for (const [id, key] of Object.entries(map)) $(id).value = bootstrap.settings[key] ?? "";
  $("s-vad").checked = !!bootstrap.settings.vad_filter;

  state.live = !!bootstrap.runtime.liveRunning;
  state.draining = !!bootstrap.runtime.liveDraining;
  state.file = !!bootstrap.runtime.fileRunning;
  progress("buffer", bootstrap.runtime.bufferLevel);
  renderModels(state.models);
  updateLiveSummary();
  updateFileSummary();
  liveUI(state.draining ? "Completamento buffer" : state.live ? "In esecuzione" : "Idle");
  fileUI(state.file ? "In esecuzione" : "Idle");
  setBackendStatus(bootstrap.runtime.backendRunning ? "ready" : "standby");
  $("log-output").textContent = bootstrap.logTail || "Nessun log persistente disponibile.";

  uiModules.forEach(module => module.hydrate?.(moduleBootstrap));
}

function appendLog(level, name, message) {
  const out = $("log-output");
  if (out.textContent.startsWith("In attesa") || out.textContent.startsWith("Nessun log")) out.textContent = "";
  out.textContent += `[${level}] ${name}: ${message}\n`;
  if ($("log-auto").checked) out.scrollTop = out.scrollHeight;
}

function friendlyError(value, context = "") {
  const raw = value && typeof value === "object"
    ? [value.message, value.detail, value.action].filter(Boolean).join("\n")
    : String(value || "Errore sconosciuto");
  const lower = raw.toLowerCase();

  if (lower.includes("stream audio #") || lower.includes("seleziona uno stream") || lower.includes("stream applicazione")) {
    return "Stream applicazione non disponibile.\nAggiorna l'elenco degli stream, avvia la riproduzione nell'applicazione e seleziona di nuovo lo stream desiderato.";
  }
  if (lower.includes("move-sink-input") || lower.includes("module-null-sink") || lower.includes("comando pipewire/pulseaudio fallito")) {
    return "Impossibile isolare lo stream applicazione.\nVerifica che pactl e PipeWire/PulseAudio siano disponibili; nessun routing permanente viene mantenuto dopo l'errore.";
  }
  if (lower.includes("audio di sistema") || lower.includes("uscita predefinita") || lower.includes("sink di firefox")) {
    return "Audio di sistema non rilevato.\nVerifica che PipeWire/PulseAudio abbia un'uscita audio predefinita oppure seleziona manualmente un dispositivo monitor.";
  }
  if (lower.includes("microfono") && (lower.includes("impossibile") || lower.includes("non trovato"))) {
    return "Microfono non rilevato.\nControlla che sia collegato e disponibile in PipeWire/PulseAudio, poi riprova o selezionalo manualmente.";
  }
  if (lower.includes("download modello fallito") || lower.includes("download modello non riuscito")) {
    return "Download del modello non riuscito.\nVerifica la connessione e usa Impostazioni → Gestione modelli per riprendere il download interrotto.";
  }
  if (lower.includes("whisper-server non trovato")) {
    return "Backend whisper-server non trovato.\nEsegui ./install.sh dalla directory di UltraTranscribr e riavvia l'applicazione.";
  }
  if (lower.includes("non compilato con sycl")) {
    return "Il backend whisper-server non dispone del supporto SYCL richiesto.\nReinstalla UltraTranscribr con ./install.sh e verifica Intel oneAPI/Level Zero.";
  }
  if (lower.includes("health check") || lower.includes("whisper-server terminato")) {
    return "whisper-server non si è avviato correttamente.\nApri la tab Log per i dettagli e verifica GPU Intel, oneAPI, porta del server e modello selezionato.";
  }
  if (lower.includes("ffmpeg conversion fallita")) {
    return "Conversione del file non riuscita.\nVerifica che il file sia leggibile e che ffmpeg supporti il codec utilizzato.";
  }
  if (lower.includes("chunk file fallito dopo")) {
    return "La trascrizione del file è fallita dopo più tentativi.\nControlla la tab Log e verifica che il backend sia ancora disponibile.";
  }
  return raw;
}
function showError(value, context = "") { notice(friendlyError(value, context), true); }

function handleRouteStatus(value) {
  if (!value || typeof value !== "object") return;
  const status = String(value.status || "");
  state.routeStatus = status;
  if (value.stream) {
    const idx = state.streams.findIndex(stream => Number(stream.id) === Number(value.stream.id));
    if (idx >= 0) state.streams[idx] = value.stream;
    updateLiveSummary({source: "application", stream: value.stream});
    $("live-stream-meta").textContent = streamMeta(value.stream);
  }
  if (status === "isolating") liveUI("Isolamento stream");
  else if (status === "playing") liveUI("In esecuzione · stream attivo");
  else if (status === "paused") liveUI("In esecuzione · stream in pausa");
  else if (status === "disconnected") {
    liveUI("Stream disconnesso");
    notice("Lo stream applicazione è scomparso. UltraTranscribr resta in ascolto e proverà a riconnetterlo se ricompare senza ambiguità.", true);
  } else if (status === "ambiguous") {
    liveUI("Stream da riselezionare");
    notice("Sono comparsi più stream compatibili: per sicurezza UltraTranscribr non ne ha scelto uno automaticamente. Ferma la sessione e seleziona lo stream corretto.", true);
  } else if (status === "reconnected") {
    liveUI("In esecuzione · riconnesso");
    notice("Stream applicazione riconnesso e nuovamente isolato.");
  } else if (status === "restored") {
    state.routeStatus = "idle";
  }
}

function event(name, payload) {
  const value = json(payload);
  let consumed = false;
  uiModules.forEach(module => {
    if (module.event?.(name, value, payload) === true) consumed = true;
  });
  if (consumed) return;

  switch (name) {
    case "backend_status_changed": setBackendStatus(value); break;
    case "process_started":
      state.live = true;
      state.draining = false;
      if (state.boot?.runtime) state.boot.runtime.backendRunning = true;
      updateLiveSummary(value && typeof value === "object" ? value : null);
      globalStatus("In uso · Live", "active");
      liveUI("In esecuzione");
      break;
    case "capture_stopped":
      state.live = false;
      state.draining = true;
      liveUI("Completamento buffer");
      break;
    case "process_stopped":
      state.live = false;
      state.draining = false;
      state.routeStatus = "idle";
      progress("buffer", 0);
      liveUI("Fermata");
      restoreBackendStatus();
      break;
    case "transcriber_drained":
      state.live = false;
      state.draining = false;
      progress("buffer", 0);
      liveUI("Completata");
      restoreBackendStatus();
      break;
    case "transcriber_status_changed": liveUI(label(value)); break;
    case "transcriber_buffer_level": progress("buffer", value); break;
    case "transcriber_new_text": text("live", value); break;
    case "transcriber_error":
      state.live = false;
      state.draining = false;
      liveUI("Errore");
      showError(value, "live");
      break;
    case "playback_stream_status_changed": handleRouteStatus(value); break;
    case "file_transcriber_status_changed":
      state.file = !["completed", "stopped", "error"].includes(String(value));
      fileUI(label(value));
      if (state.file) globalStatus("In uso · File", "active");
      else restoreBackendStatus();
      break;
    case "file_transcriber_progress": progress("file", value); break;
    case "file_transcriber_new_text": text("file", value); break;
    case "file_transcriber_full_text": text("file", value, true); break;
    case "file_transcriber_completed":
      state.file = false;
      fileUI("Completata");
      progress("file", 100);
      restoreBackendStatus();
      break;
    case "file_transcriber_error":
      state.file = false;
      fileUI("Errore");
      showError(value, "file");
      break;
    case "config_changed":
      if (state.boot && value && typeof value === "object") {
        state.boot.settings = {...state.boot.settings, ...value};
        if (value.audio_source) state.source = normalizeSource(value.audio_source);
        sourceUI();
        if (state.source === "application") refreshStreams();
        else refreshDevices();
        updateFileSummary();
      }
      break;
    case "audio_diagnostics": $("diagnostics-output").textContent = String(value); break;
    case "audio_diagnostics_error": $("diagnostics-output").textContent = String(value); showError(value, "audio"); break;
    case "model_download_started":
      state.modelBusy = value?.model || null;
      state.modelProgress[state.modelBusy] = {downloaded: 0, total: null, percent: 0};
      renderModels(state.models);
      lockSettings();
      break;
    case "model_download_progress":
      updateModelProgress(value);
      if (state.backendState === "downloading_model" && value?.model) {
        const pct = value.percent == null ? "" : ` · ${Math.max(0, Math.min(100, Number(value.percent) || 0))}%`;
        globalStatus(`Download ${modelLabels[value.model] || value.model}${pct}`, "working");
      }
      break;
    case "model_status_changed":
      state.modelBusy = null;
      state.modelProgress = {};
      lockSettings();
      refreshModels();
      break;
    case "model_download_error":
    case "model_delete_error":
      state.modelBusy = null;
      state.modelProgress = {};
      lockSettings();
      showError(value, "model");
      refreshModels();
      break;
  }
}

function label(value) {
  return ({
    idle: "Idle",
    starting: "Avvio",
    running: "In esecuzione",
    draining: "Completamento buffer",
    buffering: "Buffering",
    error: "Errore",
    preparing_vad: "Preparazione VAD",
    configuring_backend: "Configurazione backend",
    downloading_model: "Download modello",
    loading_model: "Caricamento modello",
    starting_backend: "Avvio backend",
    ready: "Pronto",
    standby: "Standby",
    isolating_vocals: "Isolamento voce",
    stopped: "Fermata",
    completed: "Completata",
  })[String(value)] || String(value);
}

async function copyValue(value) {
  const textValue = String(value || "");
  try {
    await navigator.clipboard.writeText(textValue);
    notice("Copiato negli appunti");
  } catch {
    const area = document.createElement("textarea");
    area.value = textValue;
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    notice("Copiato negli appunti");
  }
}

function startLive() {
  const handler = lastUIHandler("startLive");
  if (handler && handler.startLive() === true) return;
  const settings = state.boot?.settings || {};
  const input = selectedInputValue();
  if (state.source === "application" && !input) {
    notice("Seleziona uno stream applicazione da trascrivere", true);
    return;
  }
  updateLiveSummary();
  liveUI(state.source === "application" ? "Preparazione routing" : "Avvio");
  call("startLive", [state.source, input, settings.language || "auto"]);
}

function startFile() {
  const path = $("file-path").value;
  if (!path) { notice("Seleziona un file da trascrivere", true); return; }
  const settings = state.boot?.settings || {};
  updateFileSummary(path);
  fileUI("Avvio");
  call("startFile", [path, settings.language || "auto", settings.model_size || "large-v3-turbo", $("song-mode").checked, $("isolate-vocals").checked]);
}

function saveSettings(eventObject) {
  const handler = lastUIHandler("saveSettings");
  if (handler && handler.saveSettings(eventObject) === true) return;
  eventObject.preventDefault();
  const payload = {};
  for (const element of eventObject.currentTarget.elements) {
    if (!element.name) continue;
    if (element.type === "checkbox") payload[element.name] = element.checked;
    else if (element.type === "number") payload[element.name] = Number(element.value);
    else payload[element.name] = element.value === "" && element.name === "sink_name" ? null : element.value;
  }
  call("applySettings", [JSON.stringify(payload)], result => {
    const response = json(result);
    if (!response.ok) { showError(response.error, "settings"); return; }
    state.boot.settings = response.settings;
    state.source = normalizeSource(response.settings.audio_source);
    sourceUI();
    refreshDevices();
    updateFileSummary();
    notice("Impostazioni salvate");
  });
}

function fileName(path) {
  const parts = String(path || "").split(/[\\/]/);
  return parts[parts.length - 1] || String(path || "");
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KiB`;
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MiB`;
  return `${(bytes / 1073741824).toFixed(2)} GiB`;
}

function modelDetail(item) {
  if (item.installed) return `${formatBytes(item.size_bytes)}${item.verified ? " · hash registrato" : ""}`;
  if (Number(item.partial_bytes) > 0) return `Parziale: ${formatBytes(item.partial_bytes)}`;
  return `Minimo atteso: ${formatBytes(item.min_bytes)}`;
}

function renderModels(items) {
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
    detail.textContent = modelDetail(item);
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
    const p = state.modelProgress[item.model] || null;
    const percent = p?.percent == null ? 0 : Math.max(0, Math.min(100, Number(p.percent)));
    const fill = document.createElement("span");
    fill.style.width = `${percent}%`;
    bar.setAttribute("aria-valuenow", String(percent));
    bar.append(fill);
    const progressLabel = document.createElement("div");
    progressLabel.className = "model-progress-label";
    if (active && p) {
      progressLabel.textContent = p.total
        ? `${formatBytes(p.downloaded)} / ${formatBytes(p.total)} · ${percent}%`
        : `${formatBytes(p.downloaded)} scaricati`;
    } else if (!item.installed && Number(item.partial_bytes) > 0) {
      progressLabel.textContent = `Download riprendibile da ${formatBytes(item.partial_bytes)}`;
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
    button.onclick = () => item.installed ? requestDeleteModel(item.model) : requestDownloadModel(item.model);
    actions.append(button);
    row.append(main, progressWrap, actions);
    list.append(row);
  });
}

function updateModelProgress(payload) {
  if (!payload?.model) return;
  state.modelBusy = payload.model;
  state.modelProgress[payload.model] = {
    downloaded: Number(payload.downloaded) || 0,
    total: payload.total == null ? null : Number(payload.total),
    percent: payload.percent == null ? null : Number(payload.percent),
  };
  renderModels(state.models);
  lockSettings();
}

function refreshModels() {
  call("listModels", [], result => {
    const models = json(result);
    state.models = Array.isArray(models) ? models : [];
    renderModels(state.models);
  });
}

function requestDownloadModel(model) {
  if (sessionBusy() || state.modelBusy) return;
  state.modelBusy = model;
  state.modelProgress[model] = {downloaded: 0, total: null, percent: 0};
  renderModels(state.models);
  lockSettings();
  call("downloadModel", [model], result => {
    const response = json(result);
    if (!response?.ok) {
      state.modelBusy = null;
      state.modelProgress = {};
      renderModels(state.models);
      lockSettings();
      showError(response?.error || "Download modello non avviato", "model");
    }
  });
}

function requestDeleteModel(model) {
  if (sessionBusy() || state.modelBusy) return;
  if (!window.confirm(`Eliminare ${modelLabels[model] || model} dal disco?`)) return;
  state.modelBusy = model;
  renderModels(state.models);
  lockSettings();
  call("deleteModel", [model], result => {
    const response = json(result);
    if (!response?.ok) {
      state.modelBusy = null;
      renderModels(state.models);
      lockSettings();
      showError(response?.error || "Eliminazione modello non avviata", "model");
    }
  });
}

function bind() {
  all(".nav").forEach(button => button.onclick = () => switchView(button.dataset.view));
  all(".segment").forEach(button => button.onclick = () => {
    state.source = normalizeSource(button.dataset.source);
    sourceUI();
    refreshDevices();
  });
  $("notice-close").onclick = () => $("notice").hidden = true;
  $("live-device").onchange = updateLiveSummary;
  $("live-stream").onchange = updateSelectedStreamMeta;
  $("stream-refresh").onclick = refreshStreams;
  $("live-start").onclick = startLive;
  $("live-stop").onclick = () => call("stopLive");
  $("live-drain").onclick = () => call("stopListening");
  $("file-pick").onclick = () => call("chooseAudioFile", [], path => {
    if (path) {
      $("file-path").value = path;
      updateFileSummary(path);
    }
  });
  $("file-start").onclick = startFile;
  $("file-stop").onclick = () => call("stopFile");
  $("song-mode").onchange = eventObject => {
    $("isolate-vocals").disabled = !eventObject.target.checked;
    if (!eventObject.target.checked) $("isolate-vocals").checked = false;
  };
  $("live-copy").onclick = () => copyValue(state.liveText);
  $("file-copy").onclick = () => copyValue(state.fileText);
  $("live-clear").onclick = () => { state.liveText = ""; text("live", "", true); };
  $("file-clear").onclick = () => { state.fileText = ""; text("file", "", true); };
  $("models-refresh").onclick = refreshModels;
  $("settings-form").onsubmit = saveSettings;
  $("log-refresh").onclick = () => call("readLogTail", [300], result => {
    $("log-output").textContent = result || "Nessun log persistente disponibile.";
  });
  $("log-copy").onclick = () => copyValue($("log-output").textContent);
  $("diagnostics-run").onclick = () => {
    $("diagnostics-output").textContent = "Diagnostica in corso…";
    call("runAudioDiagnostics");
  };

  uiRuntime.bound = true;
  uiModules.forEach(module => module.bind?.());
}

function init() {
  bind();
  if (typeof QWebChannel === "undefined") {
    notice("Qt WebChannel non disponibile", true);
    return;
  }
  new QWebChannel(qt.webChannelTransport, channel => {
    backend = channel.objects.backend;
    backend.eventReceived.connect(event);
    backend.logReceived.connect(appendLog);
    call("getBootstrap", [], result => hydrate(json(result)));
  });
}

document.addEventListener("DOMContentLoaded", init);
