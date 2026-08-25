"use strict";

let fileHistorySelectedPaths = [];
let fileHistoryQueue = [];
let fileHistoryCurrentSession = null;
let fileHistoryDisplayedText = "";
let fileHistorySearchTimer = null;

function fileHistoryEnsureUI() {
  const fileView = document.querySelector('[data-panel="file"]');
  if (fileView && !$("file-queue-card")) {
    const transcript = fileView.querySelector(".transcript-card");
    transcript?.insertAdjacentHTML("beforebegin", `
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

  const historyHead = $("history-title")?.closest(".card-head");
  if (historyHead && !$("history-rename")) {
    const tools = historyHead.querySelector(".toolbar");
    if (tools) {
      const input = document.createElement("input");
      input.id = "history-name";
      input.type = "text";
      input.maxLength = 120;
      input.placeholder = "Nome sessione";
      input.setAttribute("aria-label", "Nome sessione");
      input.disabled = true;
      const button = document.createElement("button");
      button.id = "history-rename";
      button.type = "button";
      button.textContent = "Rinomina";
      button.disabled = true;
      tools.prepend(button);
      tools.prepend(input);
    }
  }

  fileHistoryEnsureRecordingUI();
}

function fileHistoryEnsureRecordingUI() {
  if ($("history-live-recording")) return;
  const meta = $("history-meta");
  if (!meta) return;
  const box = document.createElement("div");
  box.id = "history-live-recording";
  box.className = "postprocess-bar";
  box.hidden = true;
  const label = document.createElement("strong");
  label.textContent = "Registrazione microfono";
  const info = document.createElement("small");
  info.id = "history-live-recording-info";
  const audio = document.createElement("audio");
  audio.id = "history-live-recording-audio";
  audio.className = "meeting-player";
  audio.controls = true;
  audio.preload = "metadata";
  const remove = document.createElement("button");
  remove.id = "history-live-recording-delete";
  remove.type = "button";
  remove.textContent = "Elimina audio";
  box.append(label, info, audio, remove);
  meta.after(box);
}

function fileHistoryDuration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map(value => String(value).padStart(2, "0")).join(":");
}

function fileHistoryFormatBytes(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function fileHistoryShowRecording(session) {
  fileHistoryEnsureRecordingUI();
  const box = $("history-live-recording");
  const audio = $("history-live-recording-audio");
  const info = $("history-live-recording-info");
  const remove = $("history-live-recording-delete");
  if (!box || !audio || !info || !remove) return;
  box.hidden = true;
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
  if (!session || session.kind !== "live" || session.source !== "microphone") return;
  call("getSessionRecordingInfo", [session.id], raw => {
    const recording = json(raw);
    if (!recording?.exists || state.historySelected !== session.id) return;
    box.hidden = false;
    info.textContent = `${fileHistoryDuration(recording.duration_s)} · ${fileHistoryFormatBytes(recording.size_bytes)} · FLAC lossless`;
    audio.src = recording.url || "";
    audio.load();
    remove.onclick = () => call("deleteSessionRecording", [session.id], responseRaw => {
      const response = json(responseRaw);
      if (!response?.ok) {
        showError(response?.error || "Registrazione non eliminata", "history");
        return;
      }
      notice("Registrazione eliminata; la trascrizione è stata conservata");
      fileHistoryShowRecording(session);
    });
  });
}

function fileHistoryRenderSelectedPaths() {
  const input = $("file-path");
  if (!input) return;
  if (!fileHistorySelectedPaths.length) {
    input.value = "";
    input.placeholder = "Nessun file selezionato";
  } else if (fileHistorySelectedPaths.length === 1) {
    input.value = fileHistorySelectedPaths[0];
  } else {
    input.value = `${fileHistorySelectedPaths.length} file selezionati`;
    input.title = fileHistorySelectedPaths.join("\n");
  }
  const settings = state.boot?.settings || {};
  $("file-start").disabled = sessionBusy() || !fileHistorySelectedPaths.length;
  $("file-model-value").textContent = modelLabels[settings.model_size] || settings.model_size || "—";
  $("file-language-value").textContent = settings.language || "auto";
  $("file-name-value").textContent = fileHistorySelectedPaths.length === 1
    ? fileName(fileHistorySelectedPaths[0])
    : fileHistorySelectedPaths.length ? `${fileHistorySelectedPaths.length} file` : "—";
}

function fileHistorySetSelectedPaths(paths) {
  fileHistorySelectedPaths = [...new Set((Array.isArray(paths) ? paths : []).map(String).filter(Boolean))];
  fileHistoryRenderSelectedPaths();
}

function fileHistoryEnqueue(paths) {
  const clean = [...new Set((Array.isArray(paths) ? paths : []).map(String).filter(Boolean))];
  if (!clean.length) return;
  if (state.live || state.draining || state.meetingRuntime && !["completed", "error", "cancelled", "interrupted"].includes(String(state.meetingRuntime.status))) {
    notice("Ferma le sessioni attive prima di accodare file", true);
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
    fileHistoryQueue = Array.isArray(response.jobs) ? response.jobs : [];
    fileHistoryRenderQueue(fileHistoryQueue);
    fileHistorySetSelectedPaths([]);
    notice(clean.length === 1 ? "File aggiunto alla coda" : `${clean.length} file aggiunti alla coda`);
  });
}

function fileHistoryQueueStatus(value) {
  return ({queued: "In coda", starting: "Avvio", running: "In esecuzione", completed: "Completato", error: "Errore", cancelled: "Annullato"})[String(value)] || String(value || "—");
}

function fileHistoryRenderQueue(items) {
  fileHistoryQueue = Array.isArray(items) ? items : [];
  const list = $("file-queue-list");
  if (!list) return;
  list.replaceChildren();
  if (!fileHistoryQueue.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "Coda vuota.";
    list.append(empty);
    return;
  }
  fileHistoryQueue.forEach(job => {
    const row = document.createElement("div");
    row.className = `file-queue-item status-${job.status || "queued"}`;
    const info = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = fileName(job.path);
    title.title = job.path;
    const detail = document.createElement("small");
    detail.textContent = `${fileHistoryQueueStatus(job.status)} · ${Math.max(0, Math.min(100, Number(job.progress) || 0))}%${job.error ? ` · ${job.error}` : ""}`;
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

function fileHistoryExport(formatName) {
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

function fileHistoryPopulateProfiles(session) {
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

function fileHistoryShowProfile(profile) {
  if (!fileHistoryCurrentSession) return;
  const key = String(profile || "raw");
  fileHistoryDisplayedText = key === "raw"
    ? String(fileHistoryCurrentSession.text || "")
    : String(fileHistoryCurrentSession.derived_outputs?.[key] || "");
  const transcript = $("history-transcript");
  transcript.textContent = fileHistoryDisplayedText || (key === "raw" ? "Nessun testo salvato per questa sessione." : "Profilo non ancora generato.");
  transcript.classList.toggle("placeholder", !fileHistoryDisplayedText);
  $("history-generate-profile").disabled = key === "raw";
  $("history-copy").disabled = !fileHistoryDisplayedText;
}

function fileHistoryGenerateProfile() {
  if (!fileHistoryCurrentSession) return;
  const profile = $("history-profile").value;
  if (!profile || profile === "raw") return;
  call("generatePostprocess", [fileHistoryCurrentSession.id, profile], result => {
    const response = json(result);
    if (!response?.ok) {
      showError(response?.error || "Post-processing non riuscito", "history");
      return;
    }
    fileHistoryCurrentSession.derived_outputs = fileHistoryCurrentSession.derived_outputs || {};
    fileHistoryCurrentSession.derived_outputs[profile] = response.text || "";
    fileHistoryPopulateProfiles(fileHistoryCurrentSession);
    $("history-profile").value = profile;
    fileHistoryShowProfile(profile);
    notice("Profilo derivato generato senza modificare l'originale");
  });
}

function fileHistorySearch() {
  const query = $("history-search")?.value || "";
  call("searchHistory", [query, 100], result => renderHistory(json(result)));
}

function fileHistoryRename() {
  if (!state.historySelected) return;
  const name = $("history-name")?.value || "";
  call("renameHistorySession", [state.historySelected, name], result => {
    const response = json(result);
    if (!response?.ok) {
      showError(response?.error || "Rinomina non riuscita", "history");
      return;
    }
    if (fileHistoryCurrentSession?.id === state.historySelected) {
      fileHistoryCurrentSession.name = response.name || "";
      $("history-title").textContent = historyTitle(fileHistoryCurrentSession);
    }
    refreshHistoryList();
    notice(response.name ? "Nome sessione salvato" : "Nome sessione rimosso");
  });
}

const fileHistoryModule = {
  bind() {
    fileHistoryEnsureUI();
    $("file-pick").textContent = "Sfoglia multipli";
    $("file-pick").onclick = () => call("chooseAudioFiles", [], result => fileHistorySetSelectedPaths(json(result)));
    $("file-start").textContent = "Accoda";
    $("file-start").onclick = () => fileHistoryEnqueue(fileHistorySelectedPaths);
    $("file-queue-cancel").onclick = () => call("cancelFileQueue", [], result => fileHistoryRenderQueue(json(result)?.jobs || []));
    $("file-queue-clear").onclick = () => call("clearFinishedFileQueue", [], result => fileHistoryRenderQueue(json(result)?.jobs || []));
    $("history-export").onclick = () => fileHistoryExport("txt");
    $("history-export-srt").onclick = () => fileHistoryExport("srt");
    $("history-export-vtt").onclick = () => fileHistoryExport("vtt");
    $("history-copy").onclick = () => copyValue(fileHistoryDisplayedText || state.historyText);
    $("history-profile").onchange = eventObject => fileHistoryShowProfile(eventObject.target.value);
    $("history-generate-profile").onclick = fileHistoryGenerateProfile;
    $("history-search").oninput = () => {
      if (fileHistorySearchTimer !== null) clearTimeout(fileHistorySearchTimer);
      fileHistorySearchTimer = setTimeout(fileHistorySearch, 180);
    };
    $("history-rename").onclick = fileHistoryRename;
    $("history-name").onkeydown = eventObject => {
      if (eventObject.key === "Enter") {
        eventObject.preventDefault();
        fileHistoryRename();
      }
    };
  },
  hydrate(bootstrap) {
    fileHistoryEnsureUI();
    fileHistoryRenderQueue(bootstrap?.fileQueue || []);
    fileHistorySetSelectedPaths([]);
    fileHistoryPopulateProfiles(null);
  },
  event(name, value) {
    if (name === "file_queue_changed") {
      fileHistoryRenderQueue(value);
      return true;
    }
    if (name === "file_queue_job_updated") {
      const index = fileHistoryQueue.findIndex(job => job.id === value?.id);
      if (index >= 0) fileHistoryQueue[index] = value;
      else if (value) fileHistoryQueue.push(value);
      fileHistoryRenderQueue(fileHistoryQueue);
      if (["starting", "running"].includes(String(value?.status))) {
        $("file-name-value").textContent = fileName(value.path);
        $("file-name-value").title = value.path || "";
      }
      return true;
    }
    if (name === "file_drop_received") {
      const paths = Array.isArray(value) ? value : [];
      if (paths.length) fileHistoryEnqueue(paths);
      return true;
    }
    return false;
  },
  fileUI() {
    if ($("file-start")) $("file-start").disabled = sessionBusy() || !fileHistorySelectedPaths.length;
    if ($("file-pick")) $("file-pick").disabled = state.live || state.draining;
  },
  historyTitle(session, current) {
    const custom = String(session?.name || "").trim();
    return custom || current;
  },
  historySession(session) {
    fileHistoryCurrentSession = session || null;
    fileHistoryDisplayedText = String(session?.text || "");
    fileHistoryPopulateProfiles(session);
    if ($("history-profile")) $("history-profile").value = "raw";
    fileHistoryShowProfile("raw");
    const timed = Array.isArray(session?.segments) && session.segments.length > 0;
    if ($("history-export-srt")) $("history-export-srt").disabled = !timed;
    if ($("history-export-vtt")) $("history-export-vtt").disabled = !timed;
    if ($("history-name")) {
      $("history-name").disabled = !session;
      $("history-name").value = String(session?.name || "");
    }
    if ($("history-rename")) $("history-rename").disabled = !session;
    fileHistoryShowRecording(session);
  },
  historyClear() {
    fileHistoryCurrentSession = null;
    fileHistoryDisplayedText = "";
    if ($("postprocess-bar")) $("postprocess-bar").hidden = true;
    if ($("history-export-srt")) $("history-export-srt").disabled = true;
    if ($("history-export-vtt")) $("history-export-vtt").disabled = true;
    if ($("history-name")) {
      $("history-name").value = "";
      $("history-name").disabled = true;
    }
    if ($("history-rename")) $("history-rename").disabled = true;
    fileHistoryShowRecording(null);
  },
  refreshHistoryList() {
    const query = $("history-search")?.value?.trim() || "";
    if (!query) return false;
    fileHistorySearch();
    return true;
  },
};

UltraUI.register(fileHistoryModule);
fileHistoryEnsureUI();
