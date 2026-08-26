"use strict";

state.liveSessions = new Map();
state.source = "system";
state.live = false;
state.draining = false;
state.streams = [];
state.selectedStreamId = null;

const multiLivePanel = document.querySelector('[data-panel="live"]');
const multiLiveTranscript = multiLivePanel?.querySelector('.transcript-card');
if (multiLiveTranscript) multiLiveTranscript.hidden = true;

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

const sourceUxStyle = document.createElement("style");
sourceUxStyle.textContent = `
  .source-health{display:flex;align-items:center;gap:9px;margin:10px 0 0;padding:9px 11px;border-radius:var(--radius-md);background:var(--surface);box-shadow:var(--shadow-inset-small);color:var(--text-secondary);font-size:12px}
  .source-health strong{color:var(--text-primary);font-size:12px}.source-health small{display:block;color:var(--text-muted);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:460px}
  .source-health.disconnected .orb{background:var(--text-muted);box-shadow:var(--shadow-inset-small)}
  .source-health.available .orb{background:var(--accent);opacity:.7;box-shadow:0 0 0 1px var(--accent-border),0 0 7px var(--accent-glow-soft)}
  .source-health.playing .orb{background:var(--accent);box-shadow:0 0 0 1px var(--accent-border),0 0 9px var(--accent-glow)}
  #source-refresh-all{padding:8px 10px;white-space:nowrap}
`;
document.head.append(sourceUxStyle);

const sourceUxInputCard = multiLivePanel?.querySelector(".input-card");
const sourceUxHead = sourceUxInputCard?.querySelector(".card-head");
if (sourceUxHead && !$("source-refresh-all")) {
  const refreshButton = document.createElement("button");
  refreshButton.id = "source-refresh-all";
  refreshButton.type = "button";
  refreshButton.className = "button";
  refreshButton.textContent = "Aggiorna sorgenti";
  sourceUxHead.append(refreshButton);
}
if (sourceUxInputCard && !$("source-health")) {
  const health = document.createElement("div");
  health.id = "source-health";
  health.className = "source-health disconnected";
  health.setAttribute("role", "status");
  health.setAttribute("aria-live", "polite");
  health.innerHTML = '<span class="orb" aria-hidden="true"></span><div><strong id="source-health-label">Verifica sorgente</strong><small id="source-health-detail">Aggiorna per controllare la disponibilità.</small></div>';
  const actions = sourceUxInputCard.querySelector(".actions");
  sourceUxInputCard.insertBefore(health, actions || null);
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
  if (!select?.value) return "Automatico";
  return select.options[select.selectedIndex]?.textContent || select.value;
}

function devices(source, items) {
  const select = $("live-device");
  if (!select) return;
  const current = select.value;
  select.replaceChildren(new Option("Rilevamento automatico", ""));
  const flag = source === "system" ? "is_monitor" : "is_mic";
  (items || []).filter(device => !!device[flag]).forEach(device => {
    select.append(new Option(device.name + (device.hostapi_name ? ` · ${device.hostapi_name}` : ""), device.name));
  });
  if ([...select.options].some(option => option.value === current)) select.value = current;
  updateLiveSummary();
}

function streamMeta(stream) {
  if (!stream) return "Seleziona uno stream PipeWire/PulseAudio. Verrà isolato e ripristinato automaticamente al termine.";
  return `${stream.process_id ? `PID ${stream.process_id}` : "PID —"} · ${stream.process_binary || "binario —"} · ${stream.sink_name || "sink —"} · ${stream.state === "paused" ? "in pausa" : "in riproduzione"}`;
}

function selectedStream() {
  const id = Number($("live-stream")?.value);
  if (!Number.isFinite(id)) return null;
  return state.streams.find(stream => Number(stream.id) === id) || null;
}

function selectedInputValue() {
  return state.source === "application" ? $("live-stream")?.value || "" : $("live-device")?.value || "";
}

function selectedInputLabel() {
  return state.source === "application" ? selectedStream()?.display_name || "Nessuno stream" : selectedDeviceLabel();
}

function updateLiveSummary(runtime = null) {
  const settings = state.boot?.settings || {};
  const source = normalizeSource(runtime?.source || state.source || settings.audio_source || "system");
  if ($("live-source-value")) $("live-source-value").textContent = sourceLabel(source);
  if ($("live-device-value")) {
    if (runtime?.stream) $("live-device-value").textContent = runtime.stream.display_name || `Stream #${runtime.stream.id}`;
    else if (source === "application") $("live-device-value").textContent = selectedInputLabel();
    else $("live-device-value").textContent = runtime?.sink || selectedDeviceLabel();
  }
  if ($("live-model-value")) $("live-model-value").textContent = modelLabels[settings.model_size] || settings.model_size || "—";
  if ($("live-language-value")) $("live-language-value").textContent = settings.language || "auto";
}

function updateSelectedStreamMeta() {
  const stream = selectedStream();
  state.selectedStreamId = stream ? Number(stream.id) : null;
  if ($("live-stream-meta")) $("live-stream-meta").textContent = streamMeta(stream);
  updateLiveSummary();
  multiLiveSyncAggregate();
  probeSelectedAudioSource();
}

function renderPlaybackStreams(items) {
  const streams = Array.isArray(items) ? items : [];
  const select = $("live-stream");
  if (!select) return;
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

function sourceUI() {
  all(".segment").forEach(button => {
    const active = button.dataset.source === state.source;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  if ($("live-device-field")) $("live-device-field").hidden = state.source === "application";
  if ($("live-stream-field")) $("live-stream-field").hidden = state.source !== "application";
  updateLiveSummary();
  multiLiveSyncAggregate();
  if (backend) probeSelectedAudioSource();
}

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
    multiLiveAction("Ferma", () => call("stopLiveSession", [session.id]), {disabled: !active}),
    multiLiveAction("Rimuovi", () => call("removeLiveSession", [session.id]), {disabled: active}),
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
  if (active.length) globalStatus(`In uso · ${active.length} Live`, "active");
  else if (!state.file) restoreBackendStatus();
}

function renderSourceHealth(payload) {
  const health = $("source-health");
  if (!health) return;
  const value = payload && typeof payload === "object" ? payload : {};
  const status = ["available", "playing", "disconnected"].includes(value.status)
    ? value.status : "disconnected";
  health.classList.remove("available", "playing", "disconnected");
  health.classList.add(status);
  $("source-health-label").textContent = value.label || (status === "disconnected" ? "Non disponibile" : "Disponibile");
  $("source-health-detail").textContent = value.detail || sourceLabel(state.source);
}

function probeSelectedAudioSource() {
  if (!backend) return;
  call("probeAudioSource", [state.source, selectedInputValue()], result => renderSourceHealth(json(result)));
}

function multiLiveRefreshStreams() {
  call("listPlaybackStreams", [], result => {
    const response = json(result);
    if (Array.isArray(response)) renderPlaybackStreams(response);
    else {
      renderPlaybackStreams(response?.streams || []);
      if (response && response.ok === false) showError(response.error, "stream");
    }
    probeSelectedAudioSource();
  });
}

function multiLiveRefreshDevices() {
  if (state.source === "application") {
    multiLiveRefreshStreams();
    return;
  }
  call("refreshDevices", [state.source], result => {
    devices(state.source, json(result));
    probeSelectedAudioSource();
  });
}

function refreshAllAudioSources() {
  multiLiveRefreshDevices();
}

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

const liveSessionsModule = {
  hydrate(bootstrap) {
    state.source = normalizeSource(bootstrap.settings?.audio_source || "system");
    state.streams = Array.isArray(bootstrap.playbackStreams) ? bootstrap.playbackStreams : [];
    devices(state.source === "application" ? "system" : state.source, bootstrap.devices || []);
    renderPlaybackStreams(state.streams);
    sourceUI();
    state.liveSessions.clear();
    (bootstrap.liveSessions || []).forEach(multiLiveUpsert);
    multiLiveRender();
    multiLiveSyncAggregate();
    refreshAllAudioSources();
  },
  bind() {
    all(".segment").forEach(button => {
      button.onclick = () => {
        state.source = normalizeSource(button.dataset.source);
        sourceUI();
        refreshAllAudioSources();
      };
    });
    if ($("live-start")) $("live-start").onclick = () => liveSessionsModule.startLive();
    if ($("live-stop-all")) $("live-stop-all").onclick = () => call("stopAllLive");
    if ($("live-drain-all")) $("live-drain-all").onclick = () => call("drainAllLive");
    if ($("source-refresh-all")) $("source-refresh-all").onclick = refreshAllAudioSources;
    if ($("live-device")) $("live-device").onchange = () => {
      updateLiveSummary();
      probeSelectedAudioSource();
    };
    if ($("live-stream")) $("live-stream").onchange = updateSelectedStreamMeta;
    if ($("stream-refresh")) $("stream-refresh").onclick = multiLiveRefreshStreams;
  },
  isBusy() {
    return multiLiveActiveSessions().length > 0;
  },
  startLive() {
    const settings = state.boot?.settings || {};
    const input = selectedInputValue();
    if (state.file) {
      notice("Ferma la trascrizione file prima di aggiungere una sessione Live", true);
      return true;
    }
    if (state.source === "application" && !input) {
      notice("Seleziona uno stream applicazione da trascrivere", true);
      return true;
    }
    if ($("live-status")) $("live-status").textContent = "Creazione sessione";
    call("startLive", [state.source, input, settings.language || "auto"]);
    return true;
  },
  view(name) {
    if (name === "live") refreshAllAudioSources();
  },
  event(name, value) {
    switch (name) {
      case "config_changed":
        if (value?.audio_source) {
          state.source = normalizeSource(value.audio_source);
          sourceUI();
          refreshAllAudioSources();
        } else if (value && typeof value === "object") {
          updateLiveSummary();
        }
        return false;
      case "live_session_created":
      case "live_session_updated":
        multiLiveUpsert(value);
        multiLiveRender();
        multiLiveSyncAggregate();
        probeSelectedAudioSource();
        return true;
      case "live_session_buffer_level": {
        const session = state.liveSessions.get(value?.session_id);
        if (session) {
          session.buffer_level = Number(value.level) || 0;
          multiLiveRender();
        }
        return true;
      }
      case "live_session_queue_wait": {
        const session = state.liveSessions.get(value?.session_id);
        if (session) {
          session.queue_wait_ms = Number(value.wait_ms) || 0;
          session.queue_peak_ms = Number(value.peak_ms) || 0;
          session.queue_samples = (Number(session.queue_samples) || 0) + 1;
          multiLiveRender();
        }
        return true;
      }
      case "live_session_text": {
        const session = state.liveSessions.get(value?.session_id);
        if (session) {
          const addition = String(value.text || "").trim();
          session.text = (String(session.text || "").trim() + (addition ? ` ${addition}` : "")).trim();
          multiLiveRender();
        }
        return true;
      }
      case "live_session_route_status":
        multiLiveHandleRoute(value);
        probeSelectedAudioSource();
        return true;
      case "live_session_error":
        if (value?.session_id && state.liveSessions.has(value.session_id)) {
          const session = state.liveSessions.get(value.session_id);
          session.status = "error";
          session.terminal = true;
        }
        multiLiveRender();
        multiLiveSyncAggregate();
        showError(value?.error || value, "live");
        return true;
      case "live_session_removed":
        if (value?.session_id) state.liveSessions.delete(value.session_id);
        multiLiveRender();
        multiLiveSyncAggregate();
        probeSelectedAudioSource();
        return true;
      case "live_session_start_error":
      case "live_session_action_error":
        showError(value, "live");
        multiLiveSyncAggregate();
        return true;
      case "audio_devices_changed":
        if (state.source !== "application" && Array.isArray(value)) devices(state.source, value);
        return true;
      case "playback_streams_changed":
        if (Array.isArray(value)) renderPlaybackStreams(value);
        return true;
      case "audio_source_health_changed": {
        const sameSource = value?.source === state.source;
        const sameSelection = String(value?.selected_input || "") === String(selectedInputValue() || "");
        if (sameSource && sameSelection) renderSourceHealth(value);
        return true;
      }
      case "audio_discovery_error":
        showError(value, "audio");
        return true;
      default:
        return false;
    }
  },
};

UltraUI.register(liveSessionsModule);
multiLiveRender();
multiLiveSyncAggregate();
