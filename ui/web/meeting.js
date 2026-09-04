"use strict";

state.meetingRuntime = null;
let meetingCurrent = null;
let meetingHistoryId = null;
let meetingTimerAnchor = 0;
let meetingTimerBase = 0;
let meetingMode = "realtime";
let meetingFilePaths = [];
let meetingBatchQueue = [];
let meetingMicrophones = [];
let meetingMonitors = [];
let meetingStreams = [];
let meetingReviewHasAudio = false;
let meetingSources = [{ source: "microphone", selected_input: "", stream_id: null, label: "" }];

views.meeting = "RIUNIONE";

function meetingRuntimeIsBusy() {
  const runtime = state.meetingRuntime;
  return !!runtime && !["completed", "error", "cancelled", "interrupted"].includes(String(runtime.status));
}

function meetingBatchIsBusy() {
  return meetingBatchQueue.some(job => ["queued", "starting", "running", "cancelling"].includes(String(job?.status)));
}

function meetingIsBusy() {
  return meetingRuntimeIsBusy() || meetingBatchIsBusy();
}

function meetingEnsureUI() {
  if (!document.querySelector('.nav[data-view="meeting"]')) {
    const fileNav = document.querySelector('.nav[data-view="file"]');
    const button = document.createElement("button");
    button.className = "nav";
    button.dataset.view = "meeting";
    button.textContent = "Riunione";
    fileNav?.after(button);
  }

  const liveInputCard = document.querySelector('[data-panel="live"] .input-card');
  if (liveInputCard && !$("live-recording-row")) {
    const actions = liveInputCard.querySelector(".actions");
    actions?.insertAdjacentHTML("beforebegin", `
      <label class="toggle-row" id="live-recording-row" for="live-recording" hidden>
        <span><strong>Salva registrazione</strong><small>Solo Microfono. Default OFF; la copia FLAC viene associata alla sessione Live.</small></span>
        <input id="live-recording" type="checkbox"><i></i>
      </label>`);
  }

  if (!document.querySelector('[data-panel="meeting"]')) {
    const filePanel = document.querySelector('[data-panel="file"]');
    const section = document.createElement("section");
    section.className = "view scroll-view";
    section.dataset.panel = "meeting";
    section.hidden = true;
    section.innerHTML = `
      <div class="meeting-grid">
        <section class="card input-card">
          <div class="card-head"><div><p class="kicker">RIUNIONE</p><h2>Acquisisci e analizza</h2></div></div>
          <div class="meeting-mode-switch" role="group" aria-label="Modalità riunione">
            <button id="meeting-mode-realtime" class="button selected" type="button">In tempo reale</button>
            <button id="meeting-mode-file" class="button" type="button">Da registrazione</button>
          </div>

          <div id="meeting-realtime-inputs">
            <div class="card-head meeting-source-head"><div><p class="kicker">SORGENTI</p><h3>Audio realtime</h3></div><div class="toolbar"><button id="meeting-refresh-sources" type="button">Aggiorna</button><button id="meeting-add-source" type="button">Aggiungi sorgente</button></div></div>
            <div id="meeting-sources" class="meeting-source-list"></div>
            <p class="help">Puoi combinare fino a 8 sorgenti: microfono, audio di sistema e singole applicazioni. Ogni sorgente viene conservata come traccia separata e sincronizzata nel mix della riunione.</p>
          </div>

          <div id="meeting-file-input" hidden>
            <label for="meeting-file-path">Registrazioni audio o video</label>
            <div class="picker"><input id="meeting-file-path" type="text" readonly placeholder="Nessun file selezionato"><button id="meeting-pick-file" type="button">Seleziona file</button></div>
            <p class="help">Puoi selezionare più registrazioni. Verranno elaborate una alla volta con la stessa pipeline Whisper + Community-1, evitando inferenze GPU concorrenti.</p>
          </div>

          <div class="fields two meeting-common-fields">
            <div><label for="meeting-language">Lingua</label><input id="meeting-language" type="text" value="auto"></div>
            <div><label for="meeting-speaker-count">Interlocutori</label><input id="meeting-speaker-count" type="number" min="0" max="20" value="0"></div>
          </div>
          <p class="help">0 = rilevamento automatico degli interlocutori. In batch lingua e numero interlocutori vengono applicati a tutte le registrazioni selezionate.</p>
          <div class="actions">
            <button id="meeting-start" class="button selected" type="button">Avvia riunione</button>
            <button id="meeting-finish" class="button" type="button" disabled>Termina e analizza</button>
            <button id="meeting-cancel" class="button" type="button" disabled>Annulla</button>
          </div>
        </section>
        <section class="card status-card">
          <div class="card-head"><div><p class="kicker">STATO</p><h2>Pipeline riunione</h2></div><span class="orb" id="meeting-orb"></span></div>
          <dl class="metrics session-summary">
            <div><dt>Stato</dt><dd id="meeting-status">Idle</dd></div>
            <div><dt>Durata</dt><dd id="meeting-duration">00:00:00</dd></div>
            <div><dt>Sorgenti</dt><dd id="meeting-source-count">—</dd></div>
            <div><dt>Modello</dt><dd id="meeting-model">—</dd></div>
            <div><dt>Lingua</dt><dd id="meeting-language-value">—</dd></div>
          </dl>
          <div class="meeting-progress-stack">
            <div><label>Trascrizione</label><div class="progress" id="meeting-transcription-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><span></span></div></div>
            <div><label>Diarizzazione</label><div class="progress" id="meeting-diarization-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><span></span></div></div>
          </div>
          <p class="help" id="meeting-model-note">La prima diarizzazione scarica Community-1 da Hugging Face; dopo il download il modello viene riutilizzato localmente.</p>
        </section>
      </div>

      <section class="card meeting-batch-card" id="meeting-batch-card" hidden>
        <div class="card-head">
          <div><p class="kicker">BATCH</p><h2>Coda riunioni</h2></div>
          <div class="toolbar"><button id="meeting-batch-clear" type="button">Pulisci completate</button><button id="meeting-batch-cancel" type="button">Annulla coda</button></div>
        </div>
        <p class="help">La coda è FIFO e usa una sola pipeline alla volta. Un errore su una registrazione viene annotato e le successive continuano automaticamente.</p>
        <div id="meeting-batch-list" class="meeting-batch-list" aria-live="polite"><p class="empty-state">Coda vuota.</p></div>
      </section>

      <section class="card">
        <div class="card-head"><div><p class="kicker">ARCHIVIO</p><h2>Riunioni recenti</h2></div><div class="toolbar"><button id="meeting-refresh-list" type="button">Aggiorna</button></div></div>
        <div id="meeting-list" class="history-list"><p class="empty-state">Nessuna riunione salvata.</p></div>
      </section>

      <div id="meeting-review" class="meeting-review-grid" hidden>
        <section class="card">
          <div class="card-head"><div><p class="kicker">REVISIONE</p><h2 id="meeting-review-title">Riunione</h2></div></div>
          <div id="meeting-review-sources" class="meeting-review-sources"></div>
          <audio id="meeting-audio" class="meeting-player" controls preload="metadata"></audio>
          <div class="meeting-audio-actions">
            <button id="meeting-export-txt" type="button">Esporta .txt</button>
            <button id="meeting-export-srt" type="button">Esporta .srt</button>
            <button id="meeting-export-vtt" type="button">Esporta .vtt</button>
            <button id="meeting-delete-audio" type="button">Elimina audio</button>
          </div>
          <div class="fields two meeting-rediarization-controls">
            <div><label for="meeting-review-speaker-count">Interlocutori per il ricalcolo</label><input id="meeting-review-speaker-count" type="number" min="0" max="20" value="0"></div>
            <div class="actions"><button id="meeting-rerun-diarization" class="button selected" type="button" disabled>Ricalcola diarizzazione</button></div>
          </div>
          <p class="help">Riusa l'audio e i segmenti Whisper già salvati: Whisper non viene rilanciato. Le correzioni manuali e i nomi degli interlocutori vengono conservati.</p>
          <h3>Interlocutori</h3>
          <div id="meeting-speakers" class="meeting-speakers"></div>
          <details><summary>Transcript raw originale</summary><div id="meeting-raw" class="meeting-raw transcript"></div></details>
        </section>
        <section class="card">
          <div class="card-head"><div><p class="kicker">TESTO REVISIONATO</p><h2>Interventi</h2></div><small>Speaker e testo possono essere corretti senza modificare il raw Whisper.</small></div>
          <p class="help">Le nuove trascrizioni usano i timestamp parola-per-parola per separare cambi di interlocutore dentro lo stesso segmento Whisper. Le riunioni più vecchie restano modificabili manualmente.</p>
          <div id="meeting-review-list" class="meeting-review-list"></div>
        </section>
      </div>`;
    filePanel?.before(section);
  }

  const historyToolbar = document.querySelector('[data-panel="history"] .history-grid .card:nth-child(2) .card-head .toolbar');
  if (historyToolbar && !$("meeting-open-history")) {
    const button = document.createElement("button");
    button.id = "meeting-open-history";
    button.type = "button";
    button.textContent = "Apri revisione";
    button.hidden = true;
    historyToolbar.prepend(button);
  }

  const retention = $("s-retention")?.closest("section.card");
  if (retention && !$("s-meeting-audio-retention")) {
    const fields = retention.querySelector(".fields");
    fields?.insertAdjacentHTML("beforeend", `<div><label for="s-meeting-audio-retention">Audio riunioni (giorni)</label><input id="s-meeting-audio-retention" name="meeting_audio_retention_days" type="number" min="0" max="3650"></div>`);
  }
}

function meetingDuration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map(value => String(value).padStart(2, "0")).join(":");
}

function meetingFileName(path) {
  const parts = String(path || "").split(/[\\/]/);
  return parts[parts.length - 1] || String(path || "");
}

function meetingSetProgress(id, value) {
  const bar = $(id);
  if (!bar) return;
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  bar.setAttribute("aria-valuenow", String(Math.round(pct)));
  const fill = bar.querySelector("span");
  if (fill) fill.style.width = `${pct}%`;
}

function meetingStatus(value) {
  return ({
    recording: "Registrazione",
    finishing: "Chiusura registrazione",
    preparing_file: "Preparazione registrazione",
    transcribing: "Trascrizione finale",
    downloading_diarization: "Download modelli diarizzazione",
    diarizing: "Diarizzazione",
    cancelling: "Annullamento",
    completed: "Completata",
    interrupted: "Interrotta",
    cancelled: "Annullata",
    error: "Errore",
  })[String(value)] || label(value || "Idle");
}

function meetingBatchStatus(value) {
  return ({queued: "In coda", starting: "Avvio", running: "In esecuzione", cancelling: "Annullamento", completed: "Completata", error: "Errore", cancelled: "Annullata"})[String(value)] || String(value || "—");
}

function meetingRenderRuntime(runtime) {
  state.meetingRuntime = runtime || null;
  const runtimeActive = meetingRuntimeIsBusy();
  const batchActive = meetingBatchIsBusy();
  const active = runtimeActive || batchActive;
  if ($("meeting-start")) $("meeting-start").disabled = active || state.live || state.file;
  if ($("meeting-finish")) $("meeting-finish").disabled = !runtime || runtime.mode !== "realtime" || runtime.status !== "recording";
  if ($("meeting-cancel")) $("meeting-cancel").disabled = !runtimeActive || batchActive;
  if ($("meeting-mode-realtime")) $("meeting-mode-realtime").disabled = active;
  if ($("meeting-mode-file")) $("meeting-mode-file").disabled = active;
  if ($("meeting-pick-file")) $("meeting-pick-file").disabled = active;
  if ($("meeting-language")) $("meeting-language").disabled = active;
  if ($("meeting-speaker-count")) $("meeting-speaker-count").disabled = active;
  if ($("meeting-rerun-diarization")) $("meeting-rerun-diarization").disabled = active || !meetingReviewHasAudio;
  if ($("meeting-review-speaker-count")) $("meeting-review-speaker-count").disabled = active;
  if ($("meeting-batch-cancel")) $("meeting-batch-cancel").disabled = !batchActive;
  if ($("meeting-batch-clear")) $("meeting-batch-clear").disabled = !meetingBatchQueue.some(job => ["completed", "error", "cancelled"].includes(String(job?.status)));
  if ($("meeting-status")) $("meeting-status").textContent = runtime ? meetingStatus(runtime.status) : (batchActive ? "Coda riunioni" : "Idle");
  if ($("meeting-model")) $("meeting-model").textContent = runtime?.model ? (modelLabels[runtime.model] || runtime.model) : "—";
  if ($("meeting-language-value")) $("meeting-language-value").textContent = runtime?.language || "—";
  if ($("meeting-source-count")) {
    const count = Array.isArray(runtime?.sources) ? runtime.sources.length : 0;
    $("meeting-source-count").textContent = runtime ? (count || (runtime.mode === "file" ? 1 : "—")) : "—";
  }
  setOrb("meeting-orb", active);
  meetingSetProgress("meeting-transcription-progress", runtime?.progress || 0);
  meetingSetProgress("meeting-diarization-progress", runtime?.diarization_progress || 0);
  if (runtime?.status === "recording") {
    meetingTimerBase = Number(runtime.duration_s) || 0;
    meetingTimerAnchor = Date.now();
  } else if (runtime) {
    meetingTimerBase = Number(runtime.duration_s) || meetingTimerBase;
    meetingTimerAnchor = 0;
    if ($("meeting-duration")) $("meeting-duration").textContent = meetingDuration(meetingTimerBase);
  } else {
    meetingTimerBase = 0;
    meetingTimerAnchor = 0;
    if ($("meeting-duration")) $("meeting-duration").textContent = "00:00:00";
  }
  lockSettings();
  if ($("file-start")) $("file-start").disabled = active || state.live || state.file;
  if ($("file-pick")) $("file-pick").disabled = active || state.live;
  if ($("live-start")) {
    const missingStream = state.source === "application" && !$("live-stream")?.value;
    $("live-start").disabled = active || !!state.file || missingStream;
  }
}

function meetingUpdateFileSelection() {
  const input = $("meeting-file-path");
  if (!input) return;
  if (!meetingFilePaths.length) {
    input.value = "";
    input.placeholder = "Nessun file selezionato";
    input.title = "";
  } else if (meetingFilePaths.length === 1) {
    input.value = meetingFilePaths[0];
    input.title = meetingFilePaths[0];
  } else {
    input.value = `${meetingFilePaths.length} registrazioni selezionate`;
    input.title = meetingFilePaths.join("\n");
  }
  meetingUpdateModePresentation();
}

function meetingUpdateModePresentation() {
  $("meeting-mode-realtime")?.classList.toggle("selected", meetingMode === "realtime");
  $("meeting-mode-file")?.classList.toggle("selected", meetingMode === "file");
  if ($("meeting-realtime-inputs")) $("meeting-realtime-inputs").hidden = meetingMode !== "realtime";
  if ($("meeting-file-input")) $("meeting-file-input").hidden = meetingMode !== "file";
  if ($("meeting-batch-card")) $("meeting-batch-card").hidden = meetingMode !== "file";
  if ($("meeting-start")) {
    $("meeting-start").textContent = meetingMode === "file"
      ? (meetingFilePaths.length > 1 ? `Accoda ${meetingFilePaths.length} riunioni` : "Accoda registrazione")
      : "Avvia riunione";
  }
}

function meetingSetMode(mode) {
  if (meetingIsBusy()) return;
  meetingMode = mode === "file" ? "file" : "realtime";
  meetingUpdateModePresentation();
}

function meetingSourceOptions(source) {
  if (source === "microphone") return meetingMicrophones;
  if (source === "system") return meetingMonitors;
  return meetingStreams;
}

function meetingRenderSources() {
  const container = $("meeting-sources");
  if (!container) return;
  container.replaceChildren();
  meetingSources.forEach((sourceState, index) => {
    const row = document.createElement("div");
    row.className = "meeting-source-row";

    const caption = document.createElement("strong");
    caption.textContent = `Sorgente ${index + 1}`;

    const typeSelect = document.createElement("select");
    typeSelect.setAttribute("aria-label", `Tipo sorgente ${index + 1}`);
    [
      ["microphone", "Microfono"],
      ["system", "Audio di sistema"],
      ["application", "Applicazione"],
    ].forEach(([value, text]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      typeSelect.append(option);
    });
    typeSelect.value = sourceState.source;

    const inputSelect = document.createElement("select");
    inputSelect.setAttribute("aria-label", `Ingresso sorgente ${index + 1}`);
    const automatic = document.createElement("option");
    automatic.value = "";
    automatic.textContent = sourceState.source === "application" ? "Seleziona applicazione" : "Rilevamento automatico";
    inputSelect.append(automatic);
    meetingSourceOptions(sourceState.source).forEach(item => {
      const option = document.createElement("option");
      if (sourceState.source === "application") {
        option.value = String(item.id ?? "");
        option.textContent = item.display_name || `Stream #${item.id}`;
      } else {
        option.value = item.name || "";
        option.textContent = item.name + (item.hostapi_name ? ` · ${item.hostapi_name}` : "");
      }
      inputSelect.append(option);
    });
    const wanted = sourceState.source === "application" ? String(sourceState.stream_id ?? "") : String(sourceState.selected_input || "");
    if ([...inputSelect.options].some(option => option.value === wanted)) inputSelect.value = wanted;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Rimuovi";
    remove.disabled = meetingSources.length <= 1;

    typeSelect.onchange = () => {
      sourceState.source = typeSelect.value;
      sourceState.selected_input = "";
      sourceState.stream_id = null;
      sourceState.label = "";
      meetingRenderSources();
    };
    inputSelect.onchange = () => {
      if (sourceState.source === "application") {
        sourceState.stream_id = inputSelect.value ? Number(inputSelect.value) : null;
        sourceState.selected_input = "";
      } else {
        sourceState.selected_input = inputSelect.value;
        sourceState.stream_id = null;
      }
      sourceState.label = inputSelect.selectedOptions[0]?.textContent || "";
    };
    remove.onclick = () => {
      meetingSources.splice(index, 1);
      meetingRenderSources();
    };

    row.append(caption, typeSelect, inputSelect, remove);
    container.append(row);
  });
  if ($("meeting-add-source")) $("meeting-add-source").disabled = meetingSources.length >= 8 || meetingIsBusy();
}

function meetingRefreshSources() {
  call("refreshDevices", ["microphone"], raw => {
    meetingMicrophones = json(raw) || [];
    meetingRenderSources();
  });
  call("refreshDevices", ["system"], raw => {
    meetingMonitors = json(raw) || [];
    meetingRenderSources();
  });
  call("listPlaybackStreams", [], raw => {
    meetingStreams = json(raw) || [];
    meetingRenderSources();
  });
}

function meetingAddSource() {
  if (meetingSources.length >= 8 || meetingIsBusy()) return;
  const used = new Set(meetingSources.map(item => item.source));
  const source = !used.has("microphone") ? "microphone" : (!used.has("system") ? "system" : "application");
  meetingSources.push({ source, selected_input: "", stream_id: null, label: "" });
  meetingRenderSources();
}

function meetingRealtimePayload() {
  return meetingSources.map(item => ({
    source: item.source,
    selected_input: item.source === "application" ? "" : String(item.selected_input || ""),
    stream_id: item.source === "application" ? item.stream_id : null,
    label: String(item.label || ""),
  }));
}

function meetingPickFile() {
  call("chooseAudioFiles", [], raw => {
    const selected = json(raw);
    meetingFilePaths = [...new Set((Array.isArray(selected) ? selected : []).map(String).filter(Boolean))];
    meetingUpdateFileSelection();
  });
}

function meetingStart() {
  const language = $("meeting-language").value.trim() || state.boot?.settings?.language || "auto";
  const count = Math.max(0, Number($("meeting-speaker-count").value) || 0);
  if (meetingMode === "file") {
    if (!meetingFilePaths.length) {
      showError("Seleziona almeno una registrazione audio o video", "meeting");
      return;
    }
    const selected = [...meetingFilePaths];
    call("enqueueMeetingBatch", [JSON.stringify(selected), language, count], result => {
      const response = json(result);
      if (!response?.ok) {
        showError(response?.error || "Impossibile accodare le registrazioni", "meeting");
        return;
      }
      meetingFilePaths = [];
      meetingUpdateFileSelection();
      meetingRenderBatchQueue(response.jobs || []);
      notice(selected.length === 1 ? "Registrazione aggiunta alla coda Riunioni" : `${selected.length} registrazioni aggiunte alla coda Riunioni`);
    });
    return;
  }

  const payload = meetingRealtimePayload();
  const missingApplication = payload.some(item =>
    item.source === "application" && (item.stream_id === null || item.stream_id === undefined || item.stream_id === "")
  );
  if (missingApplication) {
    showError("Seleziona l'applicazione per ogni sorgente di tipo Applicazione", "meeting");
    return;
  }
  call("startMeetingRealtime", [JSON.stringify(payload), language, count], result => {
    const response = json(result);
    if (!response?.ok) {
      showError(response?.error || "Impossibile avviare la riunione", "meeting");
      return;
    }
    meetingRenderRuntime(response.meeting);
    notice(`Registrazione riunione avviata con ${payload.length} sorgent${payload.length === 1 ? "e" : "i"}`);
  });
}

function meetingFinish() {
  call("finishMeeting", [], result => {
    const response = json(result);
    if (!response?.ok) {
      showError(response?.error || "Impossibile terminare la riunione", "meeting");
      return;
    }
    meetingRenderRuntime(response.meeting);
    notice("Chiusura delle sorgenti in corso. Trascrizione finale e diarizzazione partiranno automaticamente.");
  });
}

function meetingRenderBatchQueue(items) {
  meetingBatchQueue = Array.isArray(items) ? items : [];
  const list = $("meeting-batch-list");
  if (!list) return;
  list.replaceChildren();
  if (!meetingBatchQueue.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "Coda vuota.";
    list.append(empty);
    meetingRenderRuntime(state.meetingRuntime);
    return;
  }
  meetingBatchQueue.forEach(job => {
    const row = document.createElement("div");
    row.className = `meeting-batch-item status-${job.status || "queued"}`;
    const info = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = meetingFileName(job.path);
    title.title = job.path || "";
    const detail = document.createElement("small");
    const phase = job.phase && job.phase !== job.status ? ` · ${meetingStatus(job.phase)}` : "";
    const speakers = Number(job.num_speakers) > 0 ? ` · ${job.num_speakers} interlocutori` : " · interlocutori auto";
    detail.textContent = `${meetingBatchStatus(job.status)}${phase}${speakers}${job.error ? ` · ${job.error}` : ""}`;
    info.append(title, detail);

    const progress = document.createElement("div");
    progress.className = "meeting-batch-progress-stack";
    for (const [caption, value] of [["Whisper", job.transcription_progress], ["Speaker", job.diarization_progress]]) {
      const line = document.createElement("div");
      const labelNode = document.createElement("small");
      const pct = Math.max(0, Math.min(100, Number(value) || 0));
      labelNode.textContent = `${caption} ${Math.round(pct)}%`;
      const bar = document.createElement("div");
      bar.className = "progress meeting-batch-progress";
      bar.setAttribute("role", "progressbar");
      bar.setAttribute("aria-valuemin", "0");
      bar.setAttribute("aria-valuemax", "100");
      bar.setAttribute("aria-valuenow", String(Math.round(pct)));
      const fill = document.createElement("span");
      fill.style.width = `${pct}%`;
      bar.append(fill);
      line.append(labelNode, bar);
      progress.append(line);
    }
    row.append(info, progress);
    list.append(row);
  });
  meetingRenderRuntime(state.meetingRuntime);
}

function meetingUpdateBatchJob(job) {
  if (!job?.id) return;
  const index = meetingBatchQueue.findIndex(item => item.id === job.id);
  if (index >= 0) meetingBatchQueue[index] = job;
  else meetingBatchQueue.push(job);
  meetingRenderBatchQueue(meetingBatchQueue);
}

function meetingCancelBatch() {
  if (!meetingBatchIsBusy()) return;
  if (!window.confirm("Annullare la riunione in corso e tutte quelle ancora in coda? Le riunioni già completate resteranno salvate.")) return;
  call("cancelMeetingQueue", [], raw => {
    const response = json(raw);
    if (!response?.ok) {
      showError(response?.error || "Impossibile annullare la coda Riunioni", "meeting");
      return;
    }
    meetingRenderBatchQueue(response.jobs || []);
    notice("Annullamento coda Riunioni richiesto");
  });
}

function meetingClearFinishedBatch() {
  call("clearFinishedMeetingQueue", [], raw => {
    const response = json(raw);
    if (!response?.ok) {
      showError(response?.error || "Impossibile pulire la coda Riunioni", "meeting");
      return;
    }
    meetingRenderBatchQueue(response.jobs || []);
  });
}

function meetingBatchJobForSession(sessionId) {
  const key = String(sessionId || "");
  return meetingBatchQueue.find(job => String(job?.session_id || "") === key) || null;
}

function meetingClearReview(sessionId) {
  if (meetingCurrent?.id !== String(sessionId)) return;
  const audio = $("meeting-audio");
  if (audio) {
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
  }
  meetingCurrent = null;
  meetingReviewHasAudio = false;
  if ($("meeting-review")) $("meeting-review").hidden = true;
}

function meetingDeleteSession(item) {
  const sessionId = String(item?.id || "");
  if (!sessionId) return;
  const title = item?.started_at ? new Date(item.started_at).toLocaleString() : "questa riunione";
  if (!window.confirm(`Eliminare definitivamente la riunione ${title}? Verranno rimossi trascrizione, review e audio associato.`)) return;
  call("deleteHistorySession", [sessionId], raw => {
    const response = json(raw);
    if (!response?.ok) {
      showError(response?.error || "Eliminazione riunione non riuscita", "meeting");
      return;
    }
    if (response.deleted) {
      meetingClearReview(sessionId);
      if (meetingHistoryId === sessionId) meetingHistoryId = null;
      meetingRefreshList();
      notice("Riunione eliminata definitivamente");
    } else {
      meetingRefreshList();
      notice("Riunione già assente");
    }
  });
}

function meetingRefreshList() {
  call("searchHistory", ["meeting", 100], result => {
    const items = (json(result) || []).filter(item => item?.kind === "meeting");
    const list = $("meeting-list");
    if (!list) return;
    list.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "Nessuna riunione salvata.";
      list.append(empty);
      return;
    }
    items.forEach(item => {
      const row = document.createElement("div");
      row.className = "meeting-history-entry";

      const open = document.createElement("button");
      open.type = "button";
      open.className = "history-item";
      const title = document.createElement("strong");
      title.textContent = item.started_at ? new Date(item.started_at).toLocaleString() : String(item.id || "Riunione");
      const meta = document.createElement("small");
      meta.textContent = `${meetingStatus(item.status)} · ${item.language || "auto"} · ${item.source || "meeting"}`;
      const preview = document.createElement("span");
      preview.textContent = item.text_preview || "Nessun testo";
      open.append(title, meta, preview);
      open.onclick = () => meetingLoad(item.id);

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "button compact-button meeting-history-delete";
      remove.textContent = "Elimina";
      remove.setAttribute("aria-label", `Elimina riunione ${title.textContent}`);
      remove.onclick = () => meetingDeleteSession(item);

      row.append(open, remove);
      list.append(row);
    });
  });
}

function meetingSpeakerLabel(id, names) {
  if (!id) return "Speaker ?";
  if (names?.[id]) return names[id];
  const tail = Number(String(id).split("_").pop());
  return Number.isFinite(tail) ? `Speaker ${tail + 1}` : id;
}

function meetingLoad(sessionId) {
  call("getMeetingSession", [sessionId], result => {
    const meeting = json(result);
    if (!meeting?.meeting) {
      showError("Dati riunione non disponibili", "meeting");
      return;
    }
    meetingCurrent = meeting;
    meetingRenderReview();
  });
}

function meetingRenderReviewSources(metadata) {
  const box = $("meeting-review-sources");
  if (!box) return;
  box.replaceChildren();
  const sources = metadata?.acquisition?.sources || [];
  if (!sources.length) return;
  const heading = document.createElement("h3");
  heading.textContent = "Sorgenti";
  box.append(heading);
  const list = document.createElement("div");
  list.className = "meeting-review-source-list";
  sources.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "meeting-review-source";
    const name = document.createElement("strong");
    name.textContent = item.label || item.source_path || `Sorgente ${index + 1}`;
    const meta = document.createElement("small");
    const duration = item.recording?.duration_s ? ` · ${meetingDuration(item.recording.duration_s)}` : "";
    const offset = Number(item.offset_s) > 0 ? ` · +${Number(item.offset_s).toFixed(2)} s` : "";
    meta.textContent = `${item.source || "audio"}${duration}${offset}`;
    row.append(name, meta);
    list.append(row);
  });
  box.append(list);
}

function meetingKnownSpeakerIds(metadata) {
  const ids = new Set();
  (metadata.diarization_segments || []).forEach(item => item.speaker_id && ids.add(item.speaker_id));
  (metadata.speaker_diarization_segments || []).forEach(item => item.speaker_id && ids.add(item.speaker_id));
  Object.keys(metadata.speaker_names || {}).forEach(id => ids.add(id));
  (metadata.review_segments || []).forEach(item => {
    if (item.speaker_id) ids.add(item.speaker_id);
    if (item.speaker_override) ids.add(item.speaker_override);
    (item.speaker_candidates || []).forEach(id => ids.add(id));
    (item.overlap_speakers || []).forEach(id => ids.add(id));
  });
  return [...ids].filter(id => String(id).startsWith("SPEAKER_")).sort();
}

function meetingApplySpeakerPresentation(row, status, select, item, names) {
  const manual = String(item?.speaker_override || "");
  const autoSpeaker = String(item?.speaker_id || "");
  const effective = manual || autoSpeaker;
  row.classList.toggle("meeting-uncertain", !!item?.uncertain && !manual);
  if (manual) status.textContent = `${meetingSpeakerLabel(effective, names)} · manuale`;
  else if (item?.uncertain) status.textContent = "Speaker ? · incerto";
  else status.textContent = meetingSpeakerLabel(effective, names);
  select.value = manual;
}

function meetingRenderReviewPreservingListPosition() {
  const scrollTop = $("meeting-review-list")?.scrollTop || 0;
  meetingRenderReview();
  const list = $("meeting-review-list");
  if (list) list.scrollTop = scrollTop;
}

function meetingRenderReview() {
  const meeting = meetingCurrent;
  const metadata = meeting?.meeting;
  if (!meeting || !metadata) return;
  $("meeting-review").hidden = false;
  $("meeting-review-title").textContent = meeting.started_at ? `Riunione · ${new Date(meeting.started_at).toLocaleString()}` : "Riunione";
  $("meeting-raw").textContent = meeting.text || "Nessun transcript raw.";
  if ($("meeting-review-speaker-count")) $("meeting-review-speaker-count").value = Number(metadata.num_speakers) || 0;
  meetingReviewHasAudio = false;
  meetingRenderReviewSources(metadata);

  const names = metadata.speaker_names || {};
  const speakerIds = meetingKnownSpeakerIds(metadata);
  const speakerBox = $("meeting-speakers");
  speakerBox.replaceChildren();
  speakerIds.forEach(id => {
    const row = document.createElement("label");
    row.className = "meeting-speaker-row";
    const caption = document.createElement("strong");
    caption.textContent = meetingSpeakerLabel(id, {});
    const input = document.createElement("input");
    input.type = "text";
    input.value = names[id] || "";
    input.placeholder = "Nome manuale";
    input.onchange = () => call("setMeetingSpeakerName", [meeting.id, id, input.value], responseRaw => {
      const response = json(responseRaw);
      if (response?.ok) {
        meetingCurrent = response.meeting;
        meetingRenderReviewPreservingListPosition();
      } else showError(response?.error || "Nome non salvato", "meeting");
    });
    row.append(caption, input);
    speakerBox.append(row);
  });

  const list = $("meeting-review-list");
  list.replaceChildren();
  const review = metadata.review_segments || [];
  if (!review.length) {
    const empty = document.createElement("p");
    empty.className = "meeting-empty";
    empty.textContent = "La diarizzazione non è ancora disponibile.";
    list.append(empty);
  }
  review.forEach((item, index) => {
    const hasOverlap = Array.isArray(item.overlap_speakers) && item.overlap_speakers.length > 1;

    const row = document.createElement("article");
    row.className = "meeting-review-segment";
    row.classList.toggle("meeting-overlap", hasOverlap);

    const head = document.createElement("div");
    head.className = "meeting-review-head";
    const seek = document.createElement("button");
    seek.type = "button";
    seek.textContent = meetingDuration(item.start).replace(/^00:/, "");
    seek.onclick = () => {
      const audio = $("meeting-audio");
      if (audio?.src) audio.currentTime = Number(item.start) || 0;
    };

    const speakerControls = document.createElement("div");
    speakerControls.className = "meeting-review-speaker-controls";
    const status = document.createElement("span");
    status.className = "meeting-review-speaker";

    const select = document.createElement("select");
    select.className = "meeting-speaker-select";
    select.setAttribute("aria-label", `Speaker segmento ${index + 1}`);
    const automatic = document.createElement("option");
    automatic.value = "";
    automatic.textContent = `Automatico · ${item.uncertain ? "Speaker ?" : meetingSpeakerLabel(item.speaker_id, names)}`;
    select.append(automatic);
    speakerIds.forEach(id => {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = meetingSpeakerLabel(id, names);
      select.append(option);
    });
    meetingApplySpeakerPresentation(row, status, select, item, names);
    select.onchange = () => {
      const requestedSpeaker = select.value;
      select.disabled = true;
      call("setMeetingSegmentSpeaker", [meeting.id, index, requestedSpeaker], raw => {
        select.disabled = false;
        const response = json(raw);
        if (response?.ok) {
          meetingCurrent = response.meeting;
          const updated = response.meeting?.meeting?.review_segments?.[index] || item;
          meetingApplySpeakerPresentation(row, status, select, updated, response.meeting?.meeting?.speaker_names || names);
          notice(requestedSpeaker ? "Speaker corretto manualmente" : "Assegnazione speaker riportata su Automatico");
        } else {
          meetingApplySpeakerPresentation(row, status, select, item, names);
          showError(response?.error || "Speaker non salvato", "meeting");
        }
      });
    };
    speakerControls.append(status, select);
    head.append(seek, speakerControls);

    if (hasOverlap) {
      const overlap = document.createElement("p");
      overlap.className = "meeting-overlap-warning";
      overlap.textContent = `Parlato sovrapposto rilevato: ${item.overlap_speakers.map(id => meetingSpeakerLabel(id, names)).join(" + ")}. Verifica ascoltando l'audio.`;
      row.append(head, overlap);
    } else {
      row.append(head);
    }

    const textarea = document.createElement("textarea");
    textarea.value = item.text || "";
    textarea.setAttribute("aria-label", `Testo segmento ${index + 1}`);
    const save = document.createElement("button");
    save.type = "button";
    save.textContent = "Salva correzione";
    save.onclick = () => call("editMeetingSegment", [meeting.id, index, textarea.value], raw => {
      const response = json(raw);
      if (response?.ok) {
        meetingCurrent = response.meeting;
        notice("Correzione salvata; il transcript raw è invariato");
      } else showError(response?.error || "Correzione non salvata", "meeting");
    });
    row.append(textarea, save);
    list.append(row);
  });

  call("getMeetingAudioUrl", [meeting.id], url => {
    const audio = $("meeting-audio");
    if (!audio) return;
    const value = String(url || "");
    meetingReviewHasAudio = !!value;
    if (value) audio.src = value;
    else audio.removeAttribute("src");
    audio.load();
    $("meeting-delete-audio").disabled = !value;
    if ($("meeting-rerun-diarization")) $("meeting-rerun-diarization").disabled = meetingIsBusy() || !meetingReviewHasAudio;
  });
}

function meetingRerunDiarization() {
  if (!meetingCurrent?.id || !meetingReviewHasAudio || meetingIsBusy()) return;
  const count = Math.max(0, Number($("meeting-review-speaker-count")?.value) || 0);
  call("rerunMeetingDiarization", [meetingCurrent.id, count], raw => {
    const response = json(raw);
    if (!response?.ok) {
      showError(response?.error || "Impossibile ricalcolare la diarizzazione", "meeting");
      return;
    }
    meetingRenderRuntime(response.meeting);
    notice("Ricalcolo diarizzazione avviato sui segmenti Whisper già salvati");
  });
}

function meetingExport(formatName) {
  if (!meetingCurrent?.id) return;
  call("exportMeetingFormat", [meetingCurrent.id, formatName], raw => {
    const response = json(raw);
    if (response?.cancelled) return;
    if (!response?.ok) showError(response?.error || "Export riunione fallito", "meeting");
    else notice(`Riunione esportata: ${response.path}`);
  });
}

function meetingDeleteAudio() {
  if (!meetingCurrent?.id) return;
  call("deleteMeetingAudio", [meetingCurrent.id], raw => {
    const response = json(raw);
    if (!response?.ok) showError(response?.error || "Audio non eliminato", "meeting");
    else {
      notice("Audio e tracce sorgente eliminati; trascrizione e review sono state conservate");
      meetingLoad(meetingCurrent.id);
    }
  });
}

const meetingModule = {
  bind() {
    meetingEnsureUI();
    const meetingNav = document.querySelector('.nav[data-view="meeting"]');
    if (meetingNav) meetingNav.onclick = () => {
      switchView("meeting");
      meetingRefreshSources();
      meetingRefreshList();
    };
    $("meeting-refresh-sources").onclick = meetingRefreshSources;
    $("meeting-add-source").onclick = meetingAddSource;
    $("meeting-mode-realtime").onclick = () => meetingSetMode("realtime");
    $("meeting-mode-file").onclick = () => meetingSetMode("file");
    $("meeting-pick-file").onclick = meetingPickFile;
    $("meeting-batch-clear").onclick = meetingClearFinishedBatch;
    $("meeting-batch-cancel").onclick = meetingCancelBatch;
    $("meeting-refresh-list").onclick = meetingRefreshList;
    $("meeting-start").onclick = meetingStart;
    $("meeting-finish").onclick = meetingFinish;
    $("meeting-cancel").onclick = () => call("cancelMeeting", [], raw => meetingRenderRuntime(json(raw)?.meeting));
    $("meeting-rerun-diarization").onclick = meetingRerunDiarization;
    $("meeting-export-txt").onclick = () => meetingExport("txt");
    $("meeting-export-srt").onclick = () => meetingExport("srt");
    $("meeting-export-vtt").onclick = () => meetingExport("vtt");
    $("meeting-delete-audio").onclick = meetingDeleteAudio;
    $("meeting-open-history").onclick = () => {
      if (!meetingHistoryId) return;
      switchView("meeting");
      meetingLoad(meetingHistoryId);
    };
    meetingUpdateModePresentation();
    meetingRenderSources();
    meetingRenderBatchQueue([]);
  },
  hydrate(bootstrap) {
    meetingEnsureUI();
    if ($("meeting-language")) $("meeting-language").value = bootstrap.settings?.language || "auto";
    if ($("s-meeting-audio-retention")) $("s-meeting-audio-retention").value = bootstrap.settings?.meeting_audio_retention_days ?? 30;
    meetingMicrophones = (bootstrap.devices || []).filter(device => !!device?.is_mic);
    meetingMonitors = (bootstrap.devices || []).filter(device => !!device?.is_monitor);
    meetingStreams = bootstrap.playbackStreams || [];
    meetingBatchQueue = Array.isArray(bootstrap.meetingQueue) ? bootstrap.meetingQueue : [];
    if (meetingBatchIsBusy()) meetingMode = "file";
    meetingUpdateModePresentation();
    meetingRenderSources();
    meetingRenderBatchQueue(meetingBatchQueue);
    meetingRenderRuntime(bootstrap.meetingRuntime || null);
    sourceUI();
  },
  isBusy: meetingIsBusy,
  sourceUI() {
    const row = $("live-recording-row");
    if (row) row.hidden = state.source !== "microphone";
    if (state.source !== "microphone" && $("live-recording")) $("live-recording").checked = false;
  },
  startLive() {
    const settings = state.boot?.settings || {};
    const input = selectedInputValue();
    if (state.file) {
      notice("Ferma la trascrizione file prima di aggiungere una sessione Live", true);
      return true;
    }
    if (meetingIsBusy()) {
      notice("Termina la riunione o la coda Riunioni prima di aggiungere una sessione Live", true);
      return true;
    }
    if (state.source === "application" && !input) {
      notice("Seleziona uno stream applicazione da trascrivere", true);
      return true;
    }
    const record = state.source === "microphone" && !!$("live-recording")?.checked;
    if ($("live-status")) $("live-status").textContent = "Creazione sessione";
    call("startLiveWithRecording", [state.source, input, settings.language || "auto", record]);
    return true;
  },
  historySession(session) {
    meetingHistoryId = session?.kind === "meeting" ? session.id : null;
    if ($("meeting-open-history")) $("meeting-open-history").hidden = !meetingHistoryId;
  },
  historyClear() {
    meetingHistoryId = null;
    if ($("meeting-open-history")) $("meeting-open-history").hidden = true;
  },
  event(name, value) {
    if (name === "meeting_started" || name === "meeting_updated") {
      meetingRenderRuntime(value);
      return true;
    }
    if (name === "meeting_queue_changed") {
      meetingRenderBatchQueue(value);
      return true;
    }
    if (name === "meeting_queue_job_updated") {
      meetingUpdateBatchJob(value);
      return true;
    }
    if (name === "meeting_completed") {
      const batchJob = meetingBatchJobForSession(value);
      const rediarized = state.meetingRuntime?.operation === "rediarization";
      meetingRefreshList();
      if (batchJob) {
        notice(`Riunione completata: ${meetingFileName(batchJob.path)}. La coda prosegue automaticamente.`);
      } else {
        meetingLoad(String(value));
        notice(rediarized ? "Diarizzazione ricalcolata; trascrizione e correzioni manuali sono state conservate" : "Riunione pronta per la revisione");
      }
      return true;
    }
    if (name === "meeting_error") {
      const batchJob = meetingBatchJobForSession(value?.session_id);
      if (batchJob) notice(`Errore in ${meetingFileName(batchJob.path)}; la coda proverà la registrazione successiva`, true);
      else showError(value?.error || "Errore riunione", "meeting");
      meetingRefreshList();
      return true;
    }
    if (name === "meeting_review_changed") {
      return true;
    }
    if (name === "meeting_source_status") {
      if ($("meeting-model-note") && value?.status) $("meeting-model-note").textContent = `Sorgente: ${label(value.status)}`;
      return true;
    }
    if (name === "microphone_recording_saved") return false;
    if (name === "meeting_model_progress") {
      $("meeting-model-note").textContent = `Download ${value?.model || "modello"}: ${Number(value?.percent) || 0}%`;
      return true;
    }
    if (name === "audio_devices_changed") {
      const devices = Array.isArray(value) ? value : [];
      meetingMicrophones = devices.filter(device => !!device?.is_mic);
      meetingMonitors = devices.filter(device => !!device?.is_monitor);
      meetingRenderSources();
      return false;
    }
    if (name === "playback_streams_changed") {
      meetingStreams = Array.isArray(value) ? value : [];
      meetingRenderSources();
      return false;
    }
    return false;
  },
};

UltraUI.register(meetingModule);
meetingEnsureUI();

setInterval(() => {
  if (!meetingTimerAnchor || state.meetingRuntime?.status !== "recording") return;
  const elapsed = (Date.now() - meetingTimerAnchor) / 1000;
  if ($("meeting-duration")) $("meeting-duration").textContent = meetingDuration(meetingTimerBase + elapsed);
}, 500);
