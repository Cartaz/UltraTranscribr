"use strict";

let backend = null;
const $ = id => document.getElementById(id);
const all = selector => [...document.querySelectorAll(selector)];

const state = {
  boot: null,
  file: false,
  fileText: "",
  historyText: "",
  historySelected: null,
  models: [],
  modelBusy: null,
  modelProgress: {},
  backendState: "standby",
};

const uiModules = [];
const uiRuntime = {bound: false, bootstrap: null};

function registerUIModule(module) {
  if (!module || typeof module !== "object") return;
  uiModules.push(module);
  if (uiRuntime.bound) module.bind?.();
  if (uiRuntime.bootstrap) module.hydrate?.(uiRuntime.bootstrap);
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
  return state.file || uiModules.some(module => module.isBusy?.() === true);
}

function lockSettings() {
  uiModules.forEach(module => module.lockSettings?.());
}

function hydrate(bootstrap) {
  uiRuntime.bootstrap = bootstrap;
  state.boot = bootstrap;
  state.models = Array.isArray(bootstrap.models) ? bootstrap.models : [];
  state.file = !!bootstrap.runtime.fileRunning;
  $("version").textContent = `v${bootstrap.app.version}`;
  setBackendStatus(bootstrap.runtime.backendRunning ? "ready" : "standby");
  $("log-output").textContent = bootstrap.logTail || "Nessun log persistente disponibile.";
  uiModules.forEach(module => module.hydrate?.(bootstrap));
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

function event(name, payload) {
  const value = json(payload);
  if (name === "config_changed" && state.boot && value && typeof value === "object") {
    state.boot.settings = {...state.boot.settings, ...value};
  }
  let consumed = false;
  uiModules.forEach(module => {
    if (module.event?.(name, value, payload) === true) consumed = true;
  });
  if (consumed) return;
  switch (name) {
    case "backend_status_changed": setBackendStatus(value); break;
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

function bind() {
  all(".nav").forEach(button => button.onclick = () => switchView(button.dataset.view));
  $("notice-close").onclick = () => $("notice").hidden = true;
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
