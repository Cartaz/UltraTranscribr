"use strict";

let backend = null;
const $ = id => document.getElementById(id);
const all = selector => [...document.querySelectorAll(selector)];
const state = {boot: null, source: "firefox", live: false, draining: false, file: false, liveText: "", fileText: ""};
const views = {live: "TRASCRIZIONE LIVE", file: "TRASCRIZIONE FILE", settings: "IMPOSTAZIONI", logs: "LOG E DIAGNOSTICA"};
const allowedModelChoices = ["large-v3", "large-v3-turbo", "medium"];
const modelLabels = {"large-v3": "Large v3", "large-v3-turbo": "Large v3 Turbo", medium: "Medium"};

function call(name, args = [], cb = null) {
  if (!backend || typeof backend[name] !== "function") return;
  if (cb) backend[name](...args, cb); else backend[name](...args);
}

function json(value) { try { return JSON.parse(value); } catch { return value; } }
function notice(text, error = false) { $("notice-text").textContent = text; $("notice").hidden = false; $("notice").classList.toggle("error", error); }

function switchView(name) {
  all(".nav").forEach(button => {
    const active = button.dataset.view === name;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  all(".view").forEach(panel => {
    const active = panel.dataset.panel === name;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  });
  $("eyebrow").textContent = views[name];
}

function setOrb(id, on) { $(id).classList.toggle("active", !!on); }
function globalStatus(text, on = false) { $("global-status").textContent = text; setOrb("global-orb", on); }
function progress(kind, value) { const n = Math.max(0, Math.min(100, Number(value) || 0)); $(kind + "-fill").style.width = n + "%"; $(kind + "-progress").setAttribute("aria-valuenow", String(n)); $(kind === "buffer" ? "buffer-value" : "file-progress-value").textContent = Math.round(n) + "%"; }
function text(kind, value, full = false) { const box = $(kind + "-transcript"); if (full) state[kind + "Text"] = String(value || ""); else state[kind + "Text"] += (state[kind + "Text"] ? " " : "") + String(value || ""); box.textContent = state[kind + "Text"] || "Il testo trascritto apparirà qui."; box.classList.toggle("placeholder", !state[kind + "Text"]); box.scrollTop = box.scrollHeight; }

function liveUI(status) {
  $("live-status").textContent = status;
  const busy = state.live || state.draining;
  $("live-start").disabled = busy || state.file;
  $("live-stop").disabled = !busy;
  $("live-drain").disabled = !state.live || state.draining;
  setOrb("live-orb", busy);
  lockSettings();
}

function fileUI(status) {
  $("file-status").textContent = status;
  $("file-start").disabled = state.file || state.live || state.draining;
  $("file-stop").disabled = !state.file;
  setOrb("file-orb", state.file);
  lockSettings();
}

function lockSettings() { $("settings-save").disabled = state.live || state.draining || state.file; }
function options(select, values, current) { select.innerHTML = ""; values.forEach(value => { const option = document.createElement("option"); option.value = value; option.textContent = modelLabels[value] || value; option.selected = value === current; select.append(option); }); }

function devices(source, list) {
  const select = $("live-device"), current = select.value;
  select.innerHTML = '<option value="">Rilevamento automatico</option>';
  const key = source === "firefox" ? "is_monitor" : "is_mic";
  (list || []).filter(device => device[key]).forEach(device => {
    const option = document.createElement("option");
    option.value = device.name;
    option.textContent = device.name + (device.hostapi_name ? " · " + device.hostapi_name : "");
    select.append(option);
  });
  if ([...select.options].some(option => option.value === current)) select.value = current;
}

function hydrate(bootstrap) {
  state.boot = bootstrap;
  $("version").textContent = "v" + bootstrap.app.version;
  const selectedModel = allowedModelChoices.includes(bootstrap.settings.model_size) ? bootstrap.settings.model_size : "large-v3-turbo";
  options($("s-model"), allowedModelChoices, selectedModel);
  state.source = bootstrap.settings.audio_source;
  sourceUI();
  devices(state.source, bootstrap.devices);
  $("live-model-value").textContent = modelLabels[bootstrap.settings.model_size] || bootstrap.settings.model_size;
  const map = {"s-language": "language", "s-source": "audio_source", "s-beam": "beam_size", "s-vad-silence": "vad_min_silence_ms", "s-buffer": "buffer_warn_threshold", "s-chunk": "chunk_ms", "s-channels": "channels", "s-sink": "sink_name", "s-keyword": "sink_search_keyword", "s-port": "server_port", "s-gpu": "gpu_layers", "s-compute": "compute_type", "s-width": "window_width", "s-height": "window_height"};
  for (const [id, key] of Object.entries(map)) $(id).value = bootstrap.settings[key] ?? "";
  $("s-vad").checked = !!bootstrap.settings.vad_filter;
  state.live = !!bootstrap.runtime.liveRunning;
  state.draining = !!bootstrap.runtime.liveDraining;
  state.file = !!bootstrap.runtime.fileRunning;
  progress("buffer", bootstrap.runtime.bufferLevel);
  liveUI(state.draining ? "Completamento buffer" : state.live ? "In esecuzione" : "Idle");
  fileUI(state.file ? "In esecuzione" : "Idle");
  globalStatus(bootstrap.runtime.backendRunning ? "Pronto" : "Standby", bootstrap.runtime.backendRunning);
  $("log-output").textContent = bootstrap.logTail || "Nessun log persistente disponibile.";
}

function sourceUI() { all(".segment").forEach(button => { const active = button.dataset.source === state.source; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); }); $("live-source-value").textContent = state.source === "firefox" ? "Firefox" : "Microfono"; }
function refreshDevices() { call("refreshDevices", [state.source], result => devices(state.source, json(result))); }
function appendLog(level, name, message) { const out = $("log-output"); if (out.textContent.startsWith("In attesa") || out.textContent.startsWith("Nessun log")) out.textContent = ""; out.textContent += `[${level}] ${name}: ${message}\n`; if ($("log-auto").checked) out.scrollTop = out.scrollHeight; }

function event(name, payload) {
  const value = json(payload);
  switch (name) {
    case "backend_status_changed": globalStatus(String(value || "Backend"), String(value).toLowerCase().includes("ready") || String(value).toLowerCase().includes("running")); break;
    case "process_started": state.live = true; state.draining = false; globalStatus("Trascrizione live", true); liveUI("In esecuzione"); break;
    case "capture_stopped": state.live = false; state.draining = true; liveUI("Completamento buffer"); break;
    case "process_stopped": state.live = false; state.draining = false; progress("buffer", 0); liveUI("Fermata"); globalStatus("Pronto", true); break;
    case "transcriber_drained": state.live = false; state.draining = false; progress("buffer", 0); liveUI("Completata"); globalStatus("Pronto", true); break;
    case "transcriber_status_changed": liveUI(label(value)); break;
    case "transcriber_buffer_level": progress("buffer", value); break;
    case "transcriber_new_text": text("live", value); break;
    case "transcriber_error": state.live = false; state.draining = false; liveUI("Errore"); notice(String(value), true); break;
    case "file_transcriber_status_changed": state.file = !["completed", "stopped", "error"].includes(String(value)); fileUI(label(value)); if (state.file) globalStatus("Trascrizione file", true); break;
    case "file_transcriber_progress": progress("file", value); break;
    case "file_transcriber_new_text": text("file", value); break;
    case "file_transcriber_full_text": text("file", value, true); break;
    case "file_transcriber_completed": state.file = false; fileUI("Completata"); progress("file", 100); globalStatus("Pronto", true); break;
    case "file_transcriber_error": state.file = false; fileUI("Errore"); notice(String(value), true); break;
    case "config_changed": if (state.boot && value && typeof value === "object") { state.boot.settings = {...state.boot.settings, ...value}; $("live-model-value").textContent = modelLabels[state.boot.settings.model_size] || state.boot.settings.model_size; } break;
    case "audio_diagnostics": $("diagnostics-output").textContent = String(value); break;
    case "audio_diagnostics_error": $("diagnostics-output").textContent = String(value); notice(String(value), true); break;
  }
}

function label(value) { return ({idle: "Idle", running: "In esecuzione", buffering: "Buffering", error: "Errore", loading_model: "Caricamento modello", isolating_vocals: "Isolamento voce", stopped: "Fermata", completed: "Completata"})[String(value)] || String(value); }

async function copyValue(value) {
  const textValue = String(value || "");
  try { await navigator.clipboard.writeText(textValue); notice("Copiato negli appunti"); }
  catch { const area = document.createElement("textarea"); area.value = textValue; document.body.append(area); area.select(); document.execCommand("copy"); area.remove(); notice("Copiato negli appunti"); }
}

function startLive() {
  const settings = state.boot?.settings || {};
  call("startLive", [state.source, $("live-device").value, settings.language || "auto"]);
}

function startFile() {
  const path = $("file-path").value;
  if (!path) { notice("Seleziona un file da trascrivere", true); return; }
  const settings = state.boot?.settings || {};
  call("startFile", [path, settings.language || "auto", settings.model_size || "large-v3-turbo", $("song-mode").checked, $("isolate-vocals").checked]);
}

function saveSettings(eventObject) {
  eventObject.preventDefault();
  const form = eventObject.currentTarget, payload = {};
  for (const element of form.elements) {
    if (!element.name) continue;
    if (element.type === "checkbox") payload[element.name] = element.checked;
    else if (element.type === "number") payload[element.name] = Number(element.value);
    else payload[element.name] = element.value === "" && element.name === "sink_name" ? null : element.value;
  }
  call("applySettings", [JSON.stringify(payload)], result => {
    const response = json(result);
    if (!response.ok) { notice(response.error, true); return; }
    state.boot.settings = response.settings;
    $("live-model-value").textContent = modelLabels[response.settings.model_size] || response.settings.model_size;
    notice("Impostazioni salvate");
  });
}

function bind() {
  all(".nav").forEach(button => button.onclick = () => switchView(button.dataset.view));
  all(".segment").forEach(button => button.onclick = () => { state.source = button.dataset.source; sourceUI(); refreshDevices(); });
  $("notice-close").onclick = () => $("notice").hidden = true;
  $("live-start").onclick = startLive;
  $("live-stop").onclick = () => call("stopLive");
  $("live-drain").onclick = () => call("stopListening");
  $("file-pick").onclick = () => call("chooseAudioFile", [], path => { if (path) $("file-path").value = path; });
  $("file-start").onclick = startFile;
  $("file-stop").onclick = () => call("stopFile");
  $("song-mode").onchange = eventObject => { $("isolate-vocals").disabled = !eventObject.target.checked; if (!eventObject.target.checked) $("isolate-vocals").checked = false; };
  $("live-copy").onclick = () => copyValue(state.liveText);
  $("file-copy").onclick = () => copyValue(state.fileText);
  $("live-clear").onclick = () => { state.liveText = ""; text("live", "", true); };
  $("file-clear").onclick = () => { state.fileText = ""; text("file", "", true); };
  $("settings-form").onsubmit = saveSettings;
  $("log-refresh").onclick = () => call("readLogTail", [300], result => $("log-output").textContent = result || "Nessun log persistente disponibile.");
  $("log-copy").onclick = () => copyValue($("log-output").textContent);
  $("diagnostics-run").onclick = () => { $("diagnostics-output").textContent = "Diagnostica in corso…"; call("runAudioDiagnostics"); };
}

function init() {
  bind();
  if (typeof QWebChannel === "undefined") { notice("Qt WebChannel non disponibile", true); return; }
  new QWebChannel(qt.webChannelTransport, channel => {
    backend = channel.objects.backend;
    backend.eventReceived.connect(event);
    backend.logReceived.connect(appendLog);
    call("getBootstrap", [], result => hydrate(json(result)));
  });
}

document.addEventListener("DOMContentLoaded", init);
