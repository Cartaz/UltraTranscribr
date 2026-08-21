"use strict";

let backend = null;
const $ = id => document.getElementById(id);
const all = selector => [...document.querySelectorAll(selector)];
const state = {
  boot: null,
  source: "firefox",
  live: false,
  draining: false,
  file: false,
  liveText: "",
  fileText: "",
  historyText: "",
  historySelected: null,
};
const views = {
  live: "TRASCRIZIONE LIVE",
  file: "TRASCRIZIONE FILE",
  history: "CRONOLOGIA",
  settings: "IMPOSTAZIONI",
  logs: "LOG E DIAGNOSTICA",
};
const allowedModelChoices = ["large-v3", "large-v3-turbo", "medium"];
const modelLabels = {"large-v3": "Large v3", "large-v3-turbo": "Large v3 Turbo", medium: "Medium"};

function call(name, args = [], cb = null) {
  if (!backend || typeof backend[name] !== "function") return;
  if (cb) backend[name](...args, cb); else backend[name](...args);
}

function json(value) { try { return JSON.parse(value); } catch { return value; } }
function notice(textValue, error = false) { $("notice-text").textContent = textValue; $("notice").hidden = false; $("notice").classList.toggle("error", error); }

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
  if (name === "history") refreshHistory();
}

function setOrb(id, on) { $(id).classList.toggle("active", !!on); }
function globalStatus(textValue, on = false) { $("global-status").textContent = textValue; setOrb("global-orb", on); }
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
function sessionBusy() { return state.live || state.draining || state.file; }
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
  const map = {"s-language": "language", "s-source": "audio_source", "s-beam": "beam_size", "s-vad-silence": "vad_min_silence_ms", "s-buffer": "buffer_warn_threshold", "s-chunk": "chunk_ms", "s-channels": "channels", "s-sink": "sink_name", "s-keyword": "sink_search_keyword", "s-port": "server_port", "s-gpu": "gpu_layers", "s-compute": "compute_type", "s-width": "window_width", "s-height": "window_height", "s-retention": "history_retention_days"};
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

function historyIsVisible() {
  const panel = document.querySelector('[data-panel="history"]');
  return !!panel && panel.classList.contains("active");
}

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
    case "history_changed": if (historyIsVisible()) refreshHistory(); break;
    case "history_error": notice("Autosave cronologia non riuscito: " + String(value), true); break;
    case "recovery_audio_saved": notice("Audio non trascritto salvato in Recovery", true); if (historyIsVisible()) refreshRecovery(); break;
  }
}

function label(value) { return ({idle: "Idle", starting: "Avvio", running: "In esecuzione", draining: "Completamento buffer", buffering: "Buffering", error: "Errore", loading_model: "Caricamento modello", isolating_vocals: "Isolamento voce", stopped: "Fermata", completed: "Completata"})[String(value)] || String(value); }

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

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("it-IT", {dateStyle: "short", timeStyle: "medium"});
}

function fileName(path) {
  const parts = String(path || "").split(/[\\/]/);
  return parts[parts.length - 1] || String(path || "");
}

function historyTitle(session) {
  if (session.kind === "file") {
    const name = fileName(session.source_path) || "Trascrizione file";
    return session.source === "recovery" ? `Recovery · ${name}` : name;
  }
  return session.source === "microphone" ? "Trascrizione microfono" : "Trascrizione live";
}

function renderHistory(items) {
  const list = $("history-list");
  list.replaceChildren();
  if (!Array.isArray(items) || !items.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "Nessuna trascrizione salvata.";
    list.append(empty);
    return;
  }
  items.forEach(item => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-item" + (item.id === state.historySelected ? " active" : "");
    button.dataset.sessionId = item.id;
    const title = document.createElement("strong");
    title.textContent = historyTitle(item);
    const meta = document.createElement("span");
    meta.textContent = `${formatDate(item.started_at)} · ${label(item.status)} · ${modelLabels[item.model] || item.model}`;
    const preview = document.createElement("small");
    preview.textContent = item.text_preview || "Nessun testo salvato";
    button.append(title, meta, preview);
    button.onclick = () => loadHistorySession(item.id);
    list.append(button);
  });
}

function clearHistorySelection() {
  state.historySelected = null;
  state.historyText = "";
  $("history-title").textContent = "Seleziona una trascrizione";
  $("history-meta").hidden = true;
  $("history-copy").disabled = true;
  $("history-export").disabled = true;
  $("history-delete").disabled = true;
  const transcript = $("history-transcript");
  transcript.textContent = "Il contenuto della sessione selezionata apparirà qui.";
  transcript.classList.add("placeholder");
  all(".history-item").forEach(item => item.classList.remove("active"));
}

function showHistorySession(session) {
  if (!session) return;
  state.historySelected = session.id;
  state.historyText = String(session.text || "");
  $("history-title").textContent = historyTitle(session);
  $("history-kind").textContent = session.source === "recovery" ? "Recovery" : session.kind === "file" ? "File" : "Live";
  $("history-status").textContent = label(session.status);
  $("history-model").textContent = modelLabels[session.model] || session.model || "—";
  $("history-language").textContent = session.language || "—";
  $("history-started").textContent = formatDate(session.started_at);
  $("history-source").textContent = session.kind === "file" ? (session.source_path || "—") : (session.source_path || session.source || "—");
  $("history-meta").hidden = false;
  $("history-copy").disabled = !state.historyText;
  $("history-export").disabled = false;
  $("history-delete").disabled = false;
  const transcript = $("history-transcript");
  transcript.textContent = state.historyText || "Nessun testo salvato per questa sessione.";
  transcript.classList.toggle("placeholder", !state.historyText);
  all(".history-item").forEach(item => item.classList.toggle("active", item.dataset.sessionId === session.id));
}

function loadHistorySession(sessionId) {
  call("getHistorySession", [sessionId], result => {
    const session = json(result);
    if (!session) {
      notice("Sessione non più disponibile", true);
      clearHistorySelection();
      refreshHistoryList();
      return;
    }
    showHistorySession(session);
  });
}

function exportSelectedHistory() {
  if (!state.historySelected) return;
  call("exportHistorySession", [state.historySelected], result => {
    const response = json(result);
    if (response?.cancelled) return;
    if (!response?.ok) { notice(response?.error || "Export non riuscito", true); return; }
    notice("Trascrizione esportata: " + response.path);
  });
}

function deleteSelectedHistory() {
  if (!state.historySelected) return;
  if (!window.confirm("Eliminare definitivamente questa trascrizione dalla cronologia?")) return;
  const sessionId = state.historySelected;
  call("deleteHistorySession", [sessionId], result => {
    const response = json(result);
    if (!response?.ok) { notice(response?.error || "Eliminazione non riuscita", true); return; }
    clearHistorySelection();
    refreshHistoryList();
    notice(response.deleted ? "Trascrizione eliminata" : "Trascrizione già assente");
  });
}

function refreshHistoryList() {
  call("listHistory", [80], result => renderHistory(json(result)));
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1048576).toFixed(1)} MiB`;
}

function startRecovery(item) {
  if (sessionBusy()) { notice("Ferma la trascrizione attiva prima di recuperare l'audio", true); return; }
  call("startRecovery", [item.path], result => {
    const response = json(result);
    if (!response?.ok) { notice(response?.error || "Recovery non avviato", true); return; }
    state.file = true;
    state.fileText = "";
    text("file", "", true);
    progress("file", 0);
    $("file-path").value = item.path || "";
    $("song-mode").checked = false;
    $("isolate-vocals").checked = false;
    $("isolate-vocals").disabled = true;
    fileUI("Avvio");
    switchView("file");
    notice("Ritrascrizione recovery avviata");
  });
}

function deleteRecovery(item) {
  if (sessionBusy()) { notice("Ferma la trascrizione attiva prima di eliminare un recovery", true); return; }
  if (!window.confirm(`Eliminare definitivamente ${item.name || "questo recovery WAV"}?`)) return;
  call("deleteRecovery", [item.path], result => {
    const response = json(result);
    if (!response?.ok) { notice(response?.error || "Eliminazione recovery non riuscita", true); return; }
    refreshRecovery();
    notice(response.deleted ? "Recovery eliminato" : "Recovery già assente");
  });
}

function renderRecovery(items) {
  const list = $("recovery-list");
  list.replaceChildren();
  if (!Array.isArray(items) || !items.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "Nessun audio da recuperare.";
    list.append(empty);
    return;
  }
  items.forEach(item => {
    const row = document.createElement("div");
    row.className = "recovery-item";
    const info = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item.name || "Recovery audio";
    const detail = document.createElement("small");
    detail.textContent = `${formatDate(item.modified_at)} · ${formatBytes(item.size_bytes)} · ${item.path || ""}`;
    info.append(title, detail);

    const actions = document.createElement("div");
    actions.className = "recovery-actions";
    const transcribe = document.createElement("button");
    transcribe.type = "button";
    transcribe.className = "button selected compact-button";
    transcribe.textContent = "Trascrivi";
    transcribe.disabled = sessionBusy();
    transcribe.onclick = () => startRecovery(item);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "button compact-button";
    remove.textContent = "Elimina";
    remove.disabled = sessionBusy();
    remove.onclick = () => deleteRecovery(item);
    actions.append(transcribe, remove);
    row.append(info, actions);
    list.append(row);
  });
}

function refreshRecovery() {
  call("listRecoveryAudio", [], result => renderRecovery(json(result)));
}

function refreshHistory() {
  refreshHistoryList();
  refreshRecovery();
  if (state.historySelected) loadHistorySession(state.historySelected);
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
  $("history-refresh").onclick = refreshHistory;
  $("history-copy").onclick = () => copyValue(state.historyText);
  $("history-export").onclick = exportSelectedHistory;
  $("history-delete").onclick = deleteSelectedHistory;
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
