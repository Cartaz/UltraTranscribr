"use strict";

// Phase 4 augments the existing single-session presentation without replacing
// the rest of app.js (File, History, Settings, Models and diagnostics).
state.liveSessions = new Map();

const multiLivePanel = document.querySelector('[data-panel="live"]');
const multiLiveLegacyTranscript = multiLivePanel?.querySelector('.transcript-card');
if (multiLiveLegacyTranscript) multiLiveLegacyTranscript.hidden = true;

if ($("live-start")) $("live-start").textContent = "Aggiungi sessione";
if ($("live-drain")) $("live-drain").hidden = true;
if ($("live-stop")) $("live-stop").hidden = true;
const multiLiveBufferLabel = document.querySelector('label[for="buffer-progress"]');
if (multiLiveBufferLabel) multiLiveBufferLabel.hidden = true;
if ($("buffer-progress")) $("buffer-progress").hidden = true;
if ($("buffer-value")?.parentElement) $("buffer-value").parentElement.hidden = true;

const multiLiveShell = document.createElement("section");
multiLiveShell.className = "card live-sessions-shell";
multiLiveShell.innerHTML = `
  <div class="card-head">
    <div>
      <p class="kicker">SESSIONI LIVE</p>
      <h2>Trascrizioni indipendenti</h2>
      <p id="live-session-count" class="live-session-count">0 sessioni attive</p>
    </div>
    <div class="toolbar">
      <button type="button" id="live-drain-all">Completa tutte</button>
      <button type="button" id="live-stop-all">Ferma tutte</button>
    </div>
  </div>
  <div id="live-sessions" class="live-session-list" aria-live="polite"></div>`;
if (multiLivePanel) multiLivePanel.append(multiLiveShell);

const multiLiveLegacyEvent = event;
const multiLiveLegacyHydrate = hydrate;
const multiLiveLegacyBind = bind;

function multiLiveActiveSessions() {
  return [...state.liveSessions.values()].filter(session => !session.terminal);
}

function multiLiveStatus(value) {
  const labels = {
    preparing_backend: "Preparazione backend",
    isolating: "Isolamento stream",
    starting: "Avvio",
    running: "In esecuzione",
    draining: "Completamento buffer",
    completed: "Completata",
    stopped: "Fermata",
    error: "Errore",
  };
  return labels[String(value)] || label(value);
}

function multiLiveTitle(session) {
  if (session.source_path) return String(session.source_path);
  return sourceLabel(session.source || "system");
}

function multiLiveUpsert(snapshot) {
  if (!snapshot || typeof snapshot !== "object" || !snapshot.id) return;
  const previous = state.liveSessions.get(snapshot.id) || {};
  state.liveSessions.set(snapshot.id, {
    ...previous,
    ...snapshot,
    text: snapshot.text == null ? (previous.text || "") : String(snapshot.text || ""),
  });
}

function multiLiveMetric(dl, labelText, valueText, title = "") {
  const row = document.createElement("div");
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = labelText;
  dd.textContent = valueText;
  if (title) dd.title = title;
  row.append(dt, dd);
  dl.append(row);
}

function multiLiveAction(caption, onClick, {selected = false, disabled = false} = {}) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button" + (selected ? " selected" : "");
  button.textContent = caption;
  button.disabled = !!disabled;
  button.onclick = onClick;
  return button;
}

function multiLiveRenderCard(session) {
  const card = document.createElement("article");
  card.className = "live-session-card" + (session.terminal ? " terminal" : "");
  card.dataset.sessionId = session.id;

  const head = document.createElement("div");
  head.className = "card-head";
  const titleWrap = document.createElement("div");
  titleWrap.className = "live-session-title";
  const kicker = document.createElement("p");
  kicker.className = "kicker";
  kicker.textContent = sourceLabel(session.source || "system").toUpperCase();
  const title = document.createElement("h3");
  title.textContent = multiLiveTitle(session);
  title.title = multiLiveTitle(session);
  const sessionId = document.createElement("small");
  sessionId.textContent = session.id;
  titleWrap.append(kicker, title, sessionId);

  const stateWrap = document.createElement("div");
  stateWrap.className = "live-session-state";
  const orb = document.createElement("span");
  orb.className = "orb" + (!session.terminal ? " active" : "");
  const status = document.createElement("span");
  status.textContent = multiLiveStatus(session.status || "starting");
  stateWrap.append(orb, status);
  head.append(titleWrap, stateWrap);

  const metrics = document.createElement("dl");
  metrics.className = "live-session-metrics";
  multiLiveMetric(metrics, "Modello", modelLabels[session.model] || session.model || "—");
  multiLiveMetric(metrics, "Lingua", session.language || "auto");
  multiLiveMetric(
    metrics,
    "Coda",
    `${Math.round(Number(session.queue_wait_ms) || 0)} ms`,
    `Picco ${Math.round(Number(session.queue_peak_ms) || 0)} ms · ${Number(session.queue_samples) || 0} richieste`,
  );
  multiLiveMetric(
    metrics,
    "Routing",
    session.route_status || (session.source === "application" ? "isolato" : "diretto"),
  );

  const bufferRow = document.createElement("div");
  bufferRow.className = "live-session-buffer-row";
  const bufferLabel = document.createElement("span");
  bufferLabel.textContent = "Buffer";
  const bar = document.createElement("div");
  bar.className = "progress";
  bar.setAttribute("role", "progressbar");
  bar.setAttribute("aria-valuemin", "0");
  bar.setAttribute("aria-valuemax", "100");
  const level = Math.max(0, Math.min(100, Number(session.buffer_level) || 0));
  bar.setAttribute("aria-valuenow", String(Math.round(level)));
  const fill = document.createElement("span");
  fill.style.width = `${level}%`;
  bar.append(fill);
  const bufferValue = document.createElement("span");
  bufferValue.textContent = `${Math.round(level)}%`;
  bufferRow.append(bufferLabel, bar, bufferValue);

  const transcript = document.createElement("div");
  transcript.className = "transcript live-session-transcript";
  transcript.tabIndex = 0;
  transcript.setAttribute("aria-live", "polite");
  const textValue = String(session.text || "");
  transcript.textContent = textValue || "Il testo trascritto apparirà qui.";
  transcript.classList.toggle("placeholder", !textValue);

  const actions = document.createElement("div");
  actions.className = "live-session-actions";
  const active = !session.terminal;
  actions.append(
    multiLiveAction("Copia", () => copyValue(session.text || ""), {disabled: !textValue}),
    multiLiveAction(
      "Completa buffer",
      () => call("drainLiveSession", [session.id]),
      {selected: !!session.draining, disabled: !active || !!session.draining || !session.capture_running},
    ),
    multiLiveAction(
      "Ferma",
      () => call("stopLiveSession", [session.id]),
      {disabled: !active},
    ),
    multiLiveAction(
      "Rimuovi",
      () => call("removeLiveSession", [session.id]),
      {disabled: active},
    ),
  );

  card.append(head, metrics, bufferRow, transcript, actions);
  return card;
}

function multiLiveRender() {
  const list = $("live-sessions");
  if (!list) return;
  list.replaceChildren();
  const sessions = [...state.liveSessions.values()].sort((a, b) => String(a.id).localeCompare(String(b.id)));
  if (!sessions.length) {
    const empty = document.createElement("div");
    empty.className = "live-session-empty";
    empty.textContent = "Nessuna sessione Live. Scegli una sorgente e premi “Aggiungi sessione”.";
    list.append(empty);
    return;
  }
  sessions.forEach(session => list.append(multiLiveRenderCard(session)));
}

function multiLiveSyncAggregate() {
  const active = multiLiveActiveSessions();
  const draining = active.filter(session => !!session.draining);
  const capturing = active.filter(session => !!session.capture_running && !session.draining);
  state.live = active.length > 0;
  state.draining = draining.length > 0;
  if (state.boot?.runtime) {
    state.boot.runtime.liveRunning = active.length > 0;
    state.boot.runtime.liveDraining = draining.length > 0;
    state.boot.runtime.liveSessionCount = active.length;
  }

  if ($("live-session-count")) {
    $("live-session-count").textContent = `${active.length} ${active.length === 1 ? "sessione attiva" : "sessioni attive"}`;
  }
  if ($("live-status")) {
    $("live-status").textContent = active.length
      ? `${active.length} attive${draining.length ? ` · ${draining.length} in drain` : ""}`
      : "Idle";
  }
  setOrb("live-orb", active.length > 0);

  const missingStream = state.source === "application" && !$("live-stream")?.value;
  if ($("live-start")) $("live-start").disabled = !!state.file || missingStream;
  if ($("live-stop-all")) $("live-stop-all").disabled = active.length === 0;
  if ($("live-drain-all")) $("live-drain-all").disabled = capturing.length === 0;
  if ($("file-start")) $("file-start").disabled = active.length > 0 || !!state.file;

  lockSettings();
  renderModels(state.models);
  if (active.length) globalStatus(`In uso · ${active.length} Live`, "active");
  else if (!state.file) restoreBackendStatus();
}

// Existing helpers call liveUI frequently. In multi-session mode it only
// updates the launcher/aggregate state and never disables Start merely because
// another Live session exists.
liveUI = function(statusText) {
  if (!multiLiveActiveSessions().length && statusText && $("live-status")) {
    $("live-status").textContent = statusText;
  }
  multiLiveSyncAggregate();
};

sessionBusy = function() {
  return multiLiveActiveSessions().length > 0 || !!state.file;
};

startLive = function() {
  const settings = state.boot?.settings || {};
  const input = selectedInputValue();
  if (state.file) {
    notice("Ferma la trascrizione file prima di aggiungere una sessione Live", true);
    return;
  }
  if (state.source === "application" && !input) {
    notice("Seleziona uno stream applicazione da trascrivere", true);
    return;
  }
  if ($("live-status")) $("live-status").textContent = "Creazione sessione";
  call("startLive", [state.source, input, settings.language || "auto"]);
};

function multiLiveHandleRoute(value) {
  if (!value || typeof value !== "object" || !value.session_id) return;
  const session = state.liveSessions.get(value.session_id);
  if (!session) return;
  session.route_status = String(value.status || session.route_status || "");
  if (value.stream?.display_name) session.source_path = value.stream.display_name;
  multiLiveRender();
  if (value.status === "disconnected") {
    notice(`Stream disconnesso: ${multiLiveTitle(session)}. Verrà riconnesso solo con una corrispondenza univoca.`, true);
  } else if (value.status === "ambiguous") {
    notice(`Routing ambiguo per ${multiLiveTitle(session)}: nessuno stream è stato scelto automaticamente.`, true);
  } else if (value.status === "reconnected") {
    notice(`Stream riconnesso: ${multiLiveTitle(session)}.`);
  }
}

event = function(name, payload) {
  const value = json(payload);
  switch (name) {
    case "live_session_created":
    case "live_session_updated":
      multiLiveUpsert(value);
      multiLiveRender();
      multiLiveSyncAggregate();
      if (name === "live_session_updated" && value?.terminal && historyIsVisible()) refreshHistory();
      return;
    case "live_session_buffer_level": {
      const session = state.liveSessions.get(value?.session_id);
      if (session) {
        session.buffer_level = Number(value.level) || 0;
        multiLiveRender();
      }
      return;
    }
    case "live_session_queue_wait": {
      const session = state.liveSessions.get(value?.session_id);
      if (session) {
        session.queue_wait_ms = Number(value.wait_ms) || 0;
        session.queue_peak_ms = Number(value.peak_ms) || 0;
        session.queue_samples = (Number(session.queue_samples) || 0) + 1;
        multiLiveRender();
      }
      return;
    }
    case "live_session_text": {
      const session = state.liveSessions.get(value?.session_id);
      if (session) {
        const addition = String(value.text || "").trim();
        session.text = (String(session.text || "").trim() + (addition ? ` ${addition}` : "")).trim();
        multiLiveRender();
      }
      return;
    }
    case "live_session_route_status":
      multiLiveHandleRoute(value);
      return;
    case "live_session_error":
      if (value?.session_id && state.liveSessions.has(value.session_id)) {
        const session = state.liveSessions.get(value.session_id);
        session.status = "error";
        session.terminal = true;
      }
      multiLiveRender();
      multiLiveSyncAggregate();
      showError(value?.error || value, "live");
      return;
    case "live_session_removed":
      if (value?.session_id) state.liveSessions.delete(value.session_id);
      multiLiveRender();
      multiLiveSyncAggregate();
      return;
    case "live_session_start_error":
    case "live_session_action_error":
      showError(value, "live");
      multiLiveSyncAggregate();
      return;
    case "recovery_audio_saved":
      if (value && typeof value === "object" && value.path) {
        notice("Audio non trascritto salvato in Recovery", true);
        if (historyIsVisible()) refreshRecovery();
        return;
      }
      break;
  }
  multiLiveLegacyEvent(name, payload);
};

hydrate = function(bootstrap) {
  const adjusted = {
    ...bootstrap,
    runtime: {
      ...(bootstrap.runtime || {}),
      liveRunning: false,
      liveDraining: false,
      bufferLevel: 0,
    },
  };
  multiLiveLegacyHydrate(adjusted);
  state.liveSessions.clear();
  (bootstrap.liveSessions || []).forEach(multiLiveUpsert);
  multiLiveRender();
  multiLiveSyncAggregate();
};

bind = function() {
  multiLiveLegacyBind();
  if ($("live-stop-all")) $("live-stop-all").onclick = () => call("stopAllLive");
  if ($("live-drain-all")) $("live-drain-all").onclick = () => call("drainAllLive");
};

multiLiveRender();
multiLiveSyncAggregate();
