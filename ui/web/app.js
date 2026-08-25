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
  if (uiRuntime.bound) module.bind?.();
  if (uiRuntime.bootstrap) module.hydrate?.(uiRuntime.bootstrap);
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

function call(name, args = [], callback = null) {
  if (!backend || typeof backend[name] !== "function") return;
  if (callback) backend[name](...args, callback);
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
  uiModules.forEach(module => module.view?.(name));
}

function setOrb(id, on) { $(id)?.classList.toggle("active", !!on); }

function globalStatus(textValue, mode = "idle") {
  $("global-status").textContent = textValue;
  const orb = $("global-orb");
  orb.classList.remove("active", "working", "error");
  if (mode !== "idle") orb.classList.add(mode);
}

function setBackendStatus(value) {
  const status = String(value || "standby");
  state.backendState = status;
  if (state.boot?.runtime) {
    if (status === "ready") state.boot.runtime.backendRunning = true;
    if (["standby", "error"].includes(status)) state.boot.runtime.backendRunning = false;
  }
  const mode = status === "ready" ? "active" : status === "error" ? "error" : status === "standby" ? "idle" : "working";
  globalStatus(backendLabels[status] || label(status), mode);
}

function restoreBackendStatus() {
  setBackendStatus(state.backendState === "error" ? "error" : state.boot?.runtime?.backendRunning ? "ready" : "standby");
}

function sessionBusy() {
  return state.live || state.draining || state.file || uiModules.some(module => module.isBusy?.() === true);
}

function lockSettings() {
  uiModules.forEach(module => module.lockSettings?.());
}

function normalizeSource(source) {
  return ["system", "application", "microphone"].includes(source) ? source : "system";
}

function sourceLabel(source) {
  if (source === "microphone") return "Microfono";
  if (source === "application") return "Applicazione";
  return "Audio di sistema";
}

function selectedDeviceLabel() {
  const select = $("live-device");
  if (!select.value) return "Automatico";
  return select.options[select.selectedIndex]?.textContent || select.value;
}

function devices(source, items) {
  const select = $("live-device");
  const current = select.value;
  select.replaceChildren(new Option("Rilevamento automatico", ""));
  const flag = source === "system" ? "is_monitor" : "is_mic";
  (items || []).filter(device => !!device[flag]).forEach(device => {
    const option = new Option(device.name + (device.hostapi_name ? ` · ${device.hostapi_name}` : ""), device.name);
    select.append(option);
  });
  if ([...select.options].some(option => option.value === current)) select.value = current;
  updateLiveSummary();
}

function streamMeta(stream) {
  if (!stream) return "Seleziona uno stream PipeWire/PulseAudio. Verrà isolato e ripristinato automaticamente al termine.";
  return `${stream.process_id ? `PID ${stream.process_id}` : "PID —"} · ${stream.process_binary || "binario —"} · ${stream.sink_name || "sink —"} · ${stream.state === "paused" ? "in pausa" : "in riproduzione"}`;
}

function selectedStream() {
  const id = Number($("live-stream").value);
  if (!Number.isFinite(id)) return null;
  return state.streams.find(stream => Number(stream.id) === id) || null;
}

function selectedInputValue() {
  return state.source === "application" ? $("live-stream").value : $("live-device").value;
}

function selectedInputLabel() {
  return state.source === "application" ? selectedStream()?.display_name || "Nessuno stream" : selectedDeviceLabel();
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
  select.replaceChildren(new Option(streams.length ? "Seleziona uno stream" : "Nessuno stream in riproduzione", ""));
  streams.forEach(stream => {
    const pid = stream.process_id ? `PID ${stream.process_id}` : "PID —";
    const option = new Option(`${stream.display_name || `Stream #${stream.id}`} · ${pid} · ${stream.state === "paused" ? "pausa" : "playing"}`, String(stream.id));
    option.title = `${stream.process_binary || ""} · ${stream.sink_name || ""}`;
    select.append(option);
  });
  select.value = [...select.options].some(option => option.value === previous) ? previous : "";
  updateSelectedStreamMeta();
}

function refreshStreams() {
  const handler = lastUIHandler("refreshStreams");
  if (handler?.refreshStreams() === true) return;
  call("listPlaybackStreams", [], result => {
    const response = json(result);
    renderPlaybackStreams(Array.isArray(response) ? response : response?.streams || []);
    if (!Array.isArray(response) && response?.ok === false) showError(response.error, "stream");
  });
}

function refreshDevices() {
  const handler = lastUIHandler("refreshDevices");
  if (handler?.refreshDevices() === true) return;
  if (state.source === "application") return refreshStreams();
  call("refreshDevices", [state.source], result => devices(state.source, json(result)));
}

function liveUI(status) {
  const handler = uiModules.find(module => typeof module.liveUI === "function");
  if (handler) return handler.liveUI(status);
  $("live-status").textContent = status;
  const busy = state.live || state.draining;
  $("live-start").disabled = busy || state.file || (state.source === "application" && !$("live-stream").value);
  $("live-stop").disabled = !busy;
  $("live-drain").disabled = !state.live || state.draining;
  setOrb("live-orb", busy);
  lockSettings();
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

function setLegacyBuffer(value) {
  const level = Math.max(0, Math.min(100, Number(value) || 0));
  $("buffer-fill").style.width = `${level}%`;
  $("buffer-progress").setAttribute("aria-valuenow", String(level));
  $("buffer-value").textContent = `${Math.round(level)}%`;
}

function setLegacyLiveText(value, full = false) {
  const addition = String(value || "");
  state.liveText = full ? addition : state.liveText + (state.liveText ? " " : "") + addition;
  const box = $("live-transcript");
  box.textContent = state.liveText || "Il testo trascritto apparirà qui.";
  box.classList.toggle("placeholder", !state.liveText);
  box.scrollTop = box.scrollHeight;
}

function hydrate(bootstrap) {
  uiRuntime.bootstrap = bootstrap;
  const moduleBootstrap = bootstrap;
  uiModules.forEach(module => {
    if (typeof module.transformBootstrap === "function") bootstrap = module.transformBootstrap(bootstrap) || bootstrap;
  });
  state.boot = bootstrap;
  state.models = Array.isArray(bootstrap.models) ? bootstrap.models : [];
  state.streams = Array.isArray(bootstrap.playbackStreams) ? bootstrap.playbackStreams : [];
  state.source = normalizeSource(bootstrap.settings.audio_source);
  state.live = !!bootstrap.runtime.liveRunning;
  state.draining = !!bootstrap.runtime.liveDraining;
  state.file = !!bootstrap.runtime.fileRunning;
  $("version").textContent = `v${bootstrap.app.version}`;
  devices(state.source === "application" ? "system" : state.source, bootstrap.devices);
  renderPlaybackStreams(state.streams);
  sourceUI();
  setLegacyBuffer(bootstrap.runtime.bufferLevel);
  updateLiveSummary();
  liveUI(state.draining ? "Completamento buffer" : state.live ? "In esecuzione" : "Idle");
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

function friendlyError(value) {
  const raw = value && typeof value === "object" ? [value.message, value.detail, value.action].filter(Boolean).join("\n") : String(value || "Errore sconosciuto");
  const lower = raw.toLowerCase();
  if (lower.includes("stream audio #") || lower.includes("seleziona uno stream") || lower.includes("stream applicazione")) return "Stream applicazione non disponibile.\nAggiorna l'elenco degli stream, avvia la riproduzione nell'applicazione e seleziona di nuovo lo stream desiderato.";
  if (lower.includes("move-sink-input") || lower.includes("module-null-sink") || lower.includes("comando pipewire/pulseaudio fallito")) return "Impossibile isolare lo stream applicazione.\nVerifica che pactl e PipeWire/PulseAudio siano disponibili; nessun routing permanente viene mantenuto dopo l'errore.";
  if (lower.includes("audio di sistema") || lower.includes("uscita predefinita") || lower.includes("sink di firefox")) return "Audio di sistema non rilevato.\nVerifica che PipeWire/PulseAudio abbia un'uscita audio predefinita oppure seleziona manualmente un dispositivo monitor.";
  if (lower.includes("microfono") && (lower.includes("impossibile") || lower.includes("non trovato"))) return "Microfono non rilevato.\nControlla che sia collegato e disponibile in PipeWire/PulseAudio, poi riprova o selezionalo manualmente.";
  if (lower.includes("download modello fallito") || lower.includes("download modello non riuscito")) return "Download del modello non riuscito.\nVerifica la connessione e usa Impostazioni → Gestione modelli per riprendere il download interrotto.";
  if (lower.includes("whisper-server non trovato")) return "Backend whisper-server non trovato.\nEsegui ./install.sh dalla directory di UltraTranscribr e riavvia l'applicazione.";
  if (lower.includes("non compilato con sycl")) return "Il backend whisper-server non dispone del supporto SYCL richiesto.\nReinstalla UltraTranscribr con ./install.sh e verifica Intel oneAPI/Level Zero.";
  if (lower.includes("health check") || lower.includes("whisper-server terminato")) return "whisper-server non si è avviato correttamente.\nApri la tab Log per i dettagli e verifica GPU Intel, oneAPI, porta del server e modello selezionato.";
  if (lower.includes("ffmpeg conversion fallita")) return "Conversione del file non riuscita.\nVerifica che il file sia leggibile e che ffmpeg supporti il codec utilizzato.";
  if (lower.includes("chunk file fallito dopo")) return "La trascrizione del file è fallita dopo più tentativi.\nControlla la tab Log e verifica che il backend sia ancora disponibile.";
  return raw;
}

function showError(value) { notice(friendlyError(value), true); }

function handleRouteStatus(value) {
  if (!value || typeof value !== "object") return;
  const status = String(value.status || "");
  state.routeStatus = status;
  if (value.stream) {
    const index = state.streams.findIndex(stream => Number(stream.id) === Number(value.stream.id));
    if (index >= 0) state.streams[index] = value.stream;
    updateLiveSummary({source: "application", stream: value.stream});
    $("live-stream-meta").textContent = streamMeta(value.stream);
  }
  if (status === "isolating") liveUI("Isolamento stream");
  else if (status === "playing") liveUI("In esecuzione · stream attivo");
  else if (status === "paused") liveUI("In esecuzione · stream in pausa");
  else if (status === "disconnected") { liveUI("Stream disconnesso"); notice("Lo stream applicazione è scomparso. UltraTranscribr resta in ascolto e proverà a riconnetterlo se ricompare senza ambiguità.", true); }
  else if (status === "ambiguous") { liveUI("Stream da riselezionare"); notice("Sono comparsi più stream compatibili: per sicurezza UltraTranscribr non ne ha scelto uno automaticamente. Ferma la sessione e seleziona lo stream corretto.", true); }
  else if (status === "reconnected") { liveUI("In esecuzione · riconnesso"); notice("Stream applicazione riconnesso e nuovamente isolato."); }
  else if (status === "restored") state.routeStatus = "idle";
}

function event(name, payload) {
  const value = json(payload);
  if (uiModules.some(module => module.event?.(name, value, payload) === true)) return;
  switch (name) {
    case "backend_status_changed": setBackendStatus(value); break;
    case "process_started": state.live = true; state.draining = false; updateLiveSummary(value); globalStatus("In uso · Live", "active"); liveUI("In esecuzione"); break;
    case "capture_stopped": state.live = false; state.draining = true; liveUI("Completamento buffer"); break;
    case "process_stopped": state.live = false; state.draining = false; state.routeStatus = "idle"; setLegacyBuffer(0); liveUI("Fermata"); restoreBackendStatus(); break;
    case "transcriber_drained": state.live = false; state.draining = false; setLegacyBuffer(0); liveUI("Completata"); restoreBackendStatus(); break;
    case "transcriber_status_changed": liveUI(label(value)); break;
    case "transcriber_buffer_level": setLegacyBuffer(value); break;
    case "transcriber_new_text": setLegacyLiveText(value); break;
    case "transcriber_error": state.live = false; state.draining = false; liveUI("Errore"); showError(value); break;
    case "playback_stream_status_changed": handleRouteStatus(value); break;
    case "config_changed":
      if (state.boot && value && typeof value === "object") {
        state.boot.settings = {...state.boot.settings, ...value};
        if (value.audio_source) state.source = normalizeSource(value.audio_source);
        sourceUI();
        refreshDevices();
      }
      break;
    case "audio_diagnostics": $("diagnostics-output").textContent = String(value); break;
    case "audio_diagnostics_error": $("diagnostics-output").textContent = String(value); showError(value); break;
  }
}

function label(value) {
  return ({idle: "Idle", starting: "Avvio", running: "In esecuzione", draining: "Completamento buffer", buffering: "Buffering", error: "Errore", preparing_vad: "Preparazione VAD", configuring_backend: "Configurazione backend", downloading_model: "Download modello", loading_model: "Caricamento modello", starting_backend: "Avvio backend", ready: "Pronto", standby: "Standby", isolating_vocals: "Isolamento voce", stopped: "Fermata", completed: "Completata"})[String(value)] || String(value);
}

async function copyValue(value) {
  const textValue = String(value || "");
  try { await navigator.clipboard.writeText(textValue); }
  catch {
    const area = document.createElement("textarea");
    area.value = textValue;
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  notice("Copiato negli appunti");
}

function startLive() {
  const handler = lastUIHandler("startLive");
  if (handler?.startLive() === true) return;
  const input = selectedInputValue();
  if (state.source === "application" && !input) return notice("Seleziona uno stream applicazione da trascrivere", true);
  updateLiveSummary();
  liveUI(state.source === "application" ? "Preparazione routing" : "Avvio");
  call("startLive", [state.source, input, state.boot?.settings?.language || "auto"]);
}

function bind() {
  all(".nav").forEach(button => button.onclick = () => switchView(button.dataset.view));
  all(".segment").forEach(button => button.onclick = () => { state.source = normalizeSource(button.dataset.source); sourceUI(); refreshDevices(); });
  $("notice-close").onclick = () => $("notice").hidden = true;
  $("live-device").onchange = updateLiveSummary;
  $("live-stream").onchange = updateSelectedStreamMeta;
  $("stream-refresh").onclick = refreshStreams;
  $("live-start").onclick = startLive;
  $("live-stop").onclick = () => call("stopLive");
  $("live-drain").onclick = () => call("stopListening");
  $("live-copy").onclick = () => copyValue(state.liveText);
  $("live-clear").onclick = () => setLegacyLiveText("", true);
  $("log-refresh").onclick = () => call("readLogTail", [300], result => { $("log-output").textContent = result || "Nessun log persistente disponibile."; });
  $("log-copy").onclick = () => copyValue($("log-output").textContent);
  $("diagnostics-run").onclick = () => { $("diagnostics-output").textContent = "Diagnostica in corso…"; call("runAudioDiagnostics"); };
  uiRuntime.bound = true;
  uiModules.forEach(module => module.bind?.());
}

function init() {
  bind();
  if (typeof QWebChannel === "undefined") return notice("Qt WebChannel non disponibile", true);
  new QWebChannel(qt.webChannelTransport, channel => {
    backend = channel.objects.backend;
    backend.eventReceived.connect(event);
    backend.logReceived.connect(appendLog);
    call("getBootstrap", [], result => hydrate(json(result)));
  });
}

document.addEventListener("DOMContentLoaded", init);
