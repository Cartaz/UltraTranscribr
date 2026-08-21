"use strict";

let powerSelectedPaths = [];
let powerQueue = [];
let powerCurrentSession = null;
let powerDisplayedText = "";
let powerSearchTimer = null;

function powerEnsureUI() {
  const fileView = document.querySelector('[data-panel="file"]');
  if (fileView && !$("file-queue-card")) {
    const transcript = fileView.querySelector(".transcript-card");
    transcript.insertAdjacentHTML("beforebegin", `
      <section class="card file-queue-card" id="file-queue-card">
        <div class="card-head">
          <div><p class="kicker">BATCH</p><h2>Coda file</h2></div>
          <div class="toolbar">
            <button type="button" id="file-queue-clear">Pulisci completati</button>
            <button type="button" id="file-queue-cancel">Annulla coda</button>
          </div>
        </div>
        <p class="help">Seleziona più file oppure trascinali nella finestra. La coda usa un solo worker File alla volta e conserva la cronologia di ogni elemento.</p>
        <div id="file-queue-list" class="file-queue-list" aria-live="polite"><p class="empty-state">Coda vuota.</p></div>
      </section>`);
  }

  const historyView = document.querySelector('[data-panel="history"]');
  if (historyView && !$("history-search")) {
    const firstToolbar = historyView.querySelector(".history-grid .card .card-head .toolbar");
    if (firstToolbar) {
      const search = document.createElement("input");
      search.id = "history-search";
      search.type = "search";
      search.placeholder = "Cerca testo o sorgente…";
      search.setAttribute("aria-label", "Cerca nella cronologia");
      firstToolbar.prepend(search);
    }

    const exportButton = $("history-export");
    if (exportButton) {
      exportButton.textContent = "Esporta .txt";
      for (const [id, caption] of [["history-export-srt", "Esporta .srt"], ["history-export-vtt", "Esporta .vtt"]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.id = id;
        button.textContent = caption;
        button.disabled = true;
        exportButton.after(button);
      }
    }

    const meta = $("history-meta");
    if (meta) {
      meta.insertAdjacentHTML("afterend", `
        <div class="postprocess-bar" id="postprocess-bar" hidden>
          <label for="history-profile">Vista testo</label>
          <select id="history-profile"><option value="raw">Originale</option></select>
          <button type="button" id="history-generate-profile">Genera profilo</button>
          <small>Gli output derivati vengono salvati separatamente e non modificano mai il testo originale.</small>
        </div>`);
    }
  }
}

function powerRenderSelectedPaths() {
  const input = $("file-path");
  if (!input) return;
  if (!powerSelectedPaths.length) {
    input.value = "";
    input.placeholder = "Nessun file selezionato";
  } else if (powerSelectedPaths.length === 1) {
    input.value = powerSelectedPaths[0];
  } else {
    input.value = `${powerSelectedPaths.length} file selezionati`;
    input.title = powerSelectedPaths.join("\n");
  }
  const settings = state.boot?.settings || {};
  $("file-start").disabled = state.live || state.draining || !powerSelectedPaths.length;
  $("file-model-value").textContent = modelLabels[settings.model_size] || settings.model_size || "—";
  $("file-language-value").textContent = settings.language || "auto";
  $("file-name-value").textContent = powerSelectedPaths.length === 1
    ? fileName(powerSelectedPaths[0])
    : powerSelectedPaths.length ? `${powerSelectedPaths.length} file` : "—";
}

function powerSetSelectedPaths(paths) {
  powerSelectedPaths = [...new Set((Array.isArray(paths) ? paths : []).map(String).filter(Boolean))];
  powerRenderSelectedPaths();
}

function powerEnqueue(paths) {
  const clean = [...new Set((Array.isArray(paths) ? paths : []).map(String).filter(Boolean))];
  if (!clean.length) return;
  if (state.live || state.draining) {
    notice("Ferma le sessioni Live prima di accodare file", true);
    return;
  }
  const settings = state.boot?.settings || {};
  call("enqueueFileBatch", [
    JSON.stringify(clean),
    settings.language || "auto",
    settings.model_size || "large-v3-turbo",
    $("song-mode").checked,
    $("isolate-vocals").checked,
  ], result => {
    const response = json(result);
    if (!response?.ok) {
      showError(response?.error || "Impossibile aggiungere file alla coda", "file");
      return;
    }
    powerQueue = Array.isArray(response.jobs) ? response.jobs : [];
    powerRenderQueue(powerQueue);
    powerSetSelectedPaths([]);
    notice(clean.length === 1 ? "File aggiunto alla coda" : `${clean.length} file aggiunti alla coda`);
  });
}

function powerQueueStatus(value) {
  return ({queued: "In coda", starting: "Avvio", running: "In esecuzione", completed: "Completato", error: "Errore", cancelled: "Annullato"})[String(value)] || String(value || "—");
}

function powerRenderQueue(items) {
  powerQueue = Array.isArray(items) ? items : [];
  const list = $("file-queue-list");
  if (!list) return;
  list.replaceChildren();
  if (!powerQueue.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "Coda vuota.";
    list.append(empty);
    return;
  }
  powerQueue.forEach(job => {
    const row = document.createElement("div");
    row.className = `file-queue-item status-${job.status || "queued"}`;
    const info = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = fileName(job.path);
    title.title = job.path;
    const detail = document.createElement("small");
    const suffix = job.error ? ` · ${job.error}` : "";
    detail.textContent = `${powerQueueStatus(job.status)} · ${Math.max(0, Math.min(100, Number(job.progress) || 0))}%${suffix}`;
    info.append(title, detail);
    const bar = document.createElement("div");
    bar.className = "progress file-queue-progress";
    bar.setAttribute("role", "progressbar");
    bar.setAttribute("aria-valuemin", "0");
    bar.setAttribute("aria-valuemax", "100");
    const pct = Math.max(0, Math.min(100, Number(job.progress) || 0));
    bar.setAttribute("aria-valuenow", String(pct));
    const fill = document.createElement("span");
    fill.style.width = `${pct}%`;
    bar.append(fill);
    row.append(info, bar);
    list.append(row);
  });
}

function powerExport(formatName) {
  if (!state.historySelected) return;
  const profile = formatName === "txt" ? ($("history-profile")?.value || "raw") : "raw";
  call("exportHistoryFormat", [state.historySelected, formatName, profile], result => {
    const response = json(result);
    if (response?.cancelled) return;
    if (!response?.ok) {
      showError(response?.error || "Export non riuscito", "history");
      return;
    }
    notice(`Trascrizione esportata: ${response.path}`);
  });
}

function powerPopulateProfiles(session) {
  const select = $("history-profile");
  const bar = $("postprocess-bar");
  if (!select || !bar) return;
  const previous = select.value || "raw";
  select.replaceChildren();
  const raw = document.createElement("option");
  raw.value = "raw";
  raw.textContent = "Originale";
  select.append(raw);
  const profiles = Array.isArray(state.boot?.postprocessProfiles) ? state.boot.postprocessProfiles : [];
  profiles.forEach(profile => {
    const option = document.createElement("option");
    option.value = profile.id;
    const generated = !!session?.derived_outputs?.[profile.id];
    option.textContent = `${profile.label}${generated ? " · generato" : ""}`;
    select.append(option);
  });
  select.value = [...select.options].some(option => option.value === previous) ? previous : "raw";
  bar.hidden = !session;
}

function powerShowProfile(profile) {
  if (!powerCurrentSession) return;
  const key = String(profile || "raw");
  powerDisplayedText = key === "raw"
    ? String(powerCurrentSession.text || "")
    : String(powerCurrentSession.derived_outputs?.[key] || "");
  const transcript = $("history-transcript");
  transcript.textContent = powerDisplayedText || (key === "raw" ? "Nessun testo salvato per questa sessione." : "Profilo non ancora generato.");
  transcript.classList.toggle("placeholder", !powerDisplayedText);
  $("history-generate-profile").disabled = key === "raw";
  $("history-copy").disabled = !powerDisplayedText;
}

function powerGenerateProfile() {
  if (!powerCurrentSession) return;
  const profile = $("history-profile").value;
  if (!profile || profile === "raw") return;
  call("generatePostprocess", [powerCurrentSession.id, profile], result => {
    const response = json(result);
    if (!response?.ok) {
      showError(response?.error || "Post-processing non riuscito", "history");
      return;
    }
    powerCurrentSession.derived_outputs = powerCurrentSession.derived_outputs || {};
    powerCurrentSession.derived_outputs[profile] = response.text || "";
    powerPopulateProfiles(powerCurrentSession);
    $("history-profile").value = profile;
    powerShowProfile(profile);
    notice("Profilo derivato generato senza modificare l'originale");
  });
}

function powerSearchHistory() {
  const query = $("history-search")?.value || "";
  call("searchHistory", [query, 100], result => renderHistory(json(result)));
}

function powerBind() {
  powerEnsureUI();
  $("file-pick").textContent = "Sfoglia multipli";
  $("file-pick").onclick = () => call("chooseAudioFiles", [], result => powerSetSelectedPaths(json(result)));
  $("file-start").textContent = "Accoda";
  $("file-start").onclick = () => powerEnqueue(powerSelectedPaths);
  $("file-queue-cancel").onclick = () => call("cancelFileQueue", [], result => {
    const response = json(result);
    powerRenderQueue(response?.jobs || []);
  });
  $("file-queue-clear").onclick = () => call("clearFinishedFileQueue", [], result => {
    const response = json(result);
    powerRenderQueue(response?.jobs || []);
  });
  $("history-export").onclick = () => powerExport("txt");
  $("history-export-srt").onclick = () => powerExport("srt");
  $("history-export-vtt").onclick = () => powerExport("vtt");
  $("history-copy").onclick = () => copyValue(powerDisplayedText || state.historyText);
  $("history-profile").onchange = eventObject => powerShowProfile(eventObject.target.value);
  $("history-generate-profile").onclick = powerGenerateProfile;
  $("history-search").oninput = () => {
    if (powerSearchTimer !== null) clearTimeout(powerSearchTimer);
    powerSearchTimer = setTimeout(powerSearchHistory, 180);
  };
}

function powerHydrate(bootstrap) {
  powerEnsureUI();
  powerRenderQueue(bootstrap?.fileQueue || []);
  powerSetSelectedPaths([]);
  powerPopulateProfiles(null);
}

function powerEvent(name, value) {
  if (name === "file_queue_changed") powerRenderQueue(value);
  else if (name === "file_queue_job_updated") {
    const index = powerQueue.findIndex(job => job.id === value?.id);
    if (index >= 0) powerQueue[index] = value;
    else if (value) powerQueue.push(value);
    powerRenderQueue(powerQueue);
    if (["starting", "running"].includes(String(value?.status))) {
      $("file-name-value").textContent = fileName(value.path);
      $("file-name-value").title = value.path || "";
    }
  } else if (name === "file_drop_received") {
    const paths = Array.isArray(value) ? value : [];
    if (paths.length) powerEnqueue(paths);
  }
}

const powerLegacyFileUI = fileUI;
fileUI = function(status) {
  powerLegacyFileUI(status);
  if ($("file-start")) $("file-start").disabled = state.live || state.draining || !powerSelectedPaths.length;
  if ($("file-pick")) $("file-pick").disabled = state.live || state.draining;
};

const powerLegacyShowHistorySession = showHistorySession;
showHistorySession = function(session) {
  powerLegacyShowHistorySession(session);
  powerCurrentSession = session || null;
  powerDisplayedText = String(session?.text || "");
  powerPopulateProfiles(session);
  if ($("history-profile")) $("history-profile").value = "raw";
  powerShowProfile("raw");
  const timed = Array.isArray(session?.segments) && session.segments.length > 0;
  if ($("history-export-srt")) $("history-export-srt").disabled = !timed;
  if ($("history-export-vtt")) $("history-export-vtt").disabled = !timed;
};

const powerLegacyClearHistorySelection = clearHistorySelection;
clearHistorySelection = function() {
  powerLegacyClearHistorySelection();
  powerCurrentSession = null;
  powerDisplayedText = "";
  if ($("postprocess-bar")) $("postprocess-bar").hidden = true;
  if ($("history-export-srt")) $("history-export-srt").disabled = true;
  if ($("history-export-vtt")) $("history-export-vtt").disabled = true;
};

const powerLegacyRefreshHistoryList = refreshHistoryList;
refreshHistoryList = function() {
  const query = $("history-search")?.value?.trim() || "";
  if (query) powerSearchHistory();
  else powerLegacyRefreshHistoryList();
};

const powerLegacyHydrate = hydrate;
hydrate = function(bootstrap) {
  powerLegacyHydrate(bootstrap);
  powerHydrate(bootstrap);
};

const powerLegacyEvent = event;
event = function(name, payload) {
  powerLegacyEvent(name, payload);
  powerEvent(name, json(payload));
};

const powerLegacyBind = bind;
bind = function() {
  powerLegacyBind();
  powerBind();
};

function powerLateInit() {
  powerEnsureUI();
  powerBind();
  if (state.boot) powerHydrate(state.boot);
  // If this dynamically loaded module arrived after WebChannel connected,
  // attach only the Phase 9 listener; otherwise app.js will connect the
  // wrapped global event() function during its normal initialization.
  if (backend && backend.eventReceived && typeof backend.eventReceived.connect === "function") {
    backend.eventReceived.connect((name, payload) => powerEvent(name, json(payload)));
  }
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", powerLateInit);
else powerLateInit();
