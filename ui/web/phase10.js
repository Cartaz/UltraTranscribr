"use strict";

state.meetingRuntime = null;
let phase10Meeting = null;
let phase10HistoryMeetingId = null;
let phase10TimerAnchor = 0;
let phase10TimerBase = 0;

views.meeting = "RIUNIONE";

function phase10EnsureUI() {
  if (!document.querySelector('.nav[data-view="meeting"]')) {
    const fileNav = document.querySelector('.nav[data-view="file"]');
    const button = document.createElement("button");
    button.className = "nav";
    button.dataset.view = "meeting";
    button.textContent = "Riunione";
    button.onclick = () => {
      switchView("meeting");
      phase10RefreshMeetingDevices();
      phase10RefreshMeetingList();
    };
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
          <div class="card-head"><div><p class="kicker">RIUNIONE</p><h2>Registra e analizza</h2></div></div>
          <label for="meeting-device">Microfono</label>
          <div class="picker"><select id="meeting-device"><option value="">Rilevamento automatico</option></select><button id="meeting-refresh-devices" type="button">Aggiorna</button></div>
          <div class="fields two">
            <div><label for="meeting-language">Lingua</label><input id="meeting-language" type="text" value="auto"></div>
            <div><label for="meeting-speaker-count">Interlocutori</label><input id="meeting-speaker-count" type="number" min="0" max="20" value="0"></div>
          </div>
          <p class="help">0 = rilevamento automatico. La registrazione è sempre attiva in modalità Riunione e viene salvata localmente.</p>
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
            <div><dt>Modello</dt><dd id="meeting-model">—</dd></div>
            <div><dt>Lingua</dt><dd id="meeting-language-value">—</dd></div>
          </dl>
          <div class="meeting-progress-stack">
            <div><label>Trascrizione</label><div class="progress" id="meeting-transcription-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><span></span></div></div>
            <div><label>Diarizzazione</label><div class="progress" id="meeting-diarization-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><span></span></div></div>
          </div>
          <p class="help" id="meeting-model-note">La prima diarizzazione scarica automaticamente i modelli ONNX locali.</p>
        </section>
      </div>

      <section class="card">
        <div class="card-head"><div><p class="kicker">ARCHIVIO</p><h2>Riunioni recenti</h2></div><div class="toolbar"><button id="meeting-refresh-list" type="button">Aggiorna</button></div></div>
        <div id="meeting-list" class="history-list"><p class="empty-state">Nessuna riunione salvata.</p></div>
      </section>

      <div id="meeting-review" class="meeting-review-grid" hidden>
        <section class="card">
          <div class="card-head"><div><p class="kicker">REVISIONE</p><h2 id="meeting-review-title">Riunione</h2></div></div>
          <audio id="meeting-audio" class="meeting-player" controls preload="metadata"></audio>
          <div class="meeting-audio-actions">
            <button id="meeting-export-txt" type="button">Esporta .txt</button>
            <button id="meeting-export-srt" type="button">Esporta .srt</button>
            <button id="meeting-export-vtt" type="button">Esporta .vtt</button>
            <button id="meeting-delete-audio" type="button">Elimina audio</button>
          </div>
          <h3>Interlocutori</h3>
          <div id="meeting-speakers" class="meeting-speakers"></div>
          <details><summary>Transcript raw originale</summary><div id="meeting-raw" class="meeting-raw transcript"></div></details>
        </section>
        <section class="card">
          <div class="card-head"><div><p class="kicker">TESTO REVISIONATO</p><h2>Interventi</h2></div><small>Le modifiche non sovrascrivono Whisper raw.</small></div>
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
    button.onclick = () => {
      if (!phase10HistoryMeetingId) return;
      switchView("meeting");
      phase10LoadMeeting(phase10HistoryMeetingId);
    };
    historyToolbar.prepend(button);
  }

  const retention = $("s-retention")?.closest("section.card");
  if (retention && !$("s-meeting-audio-retention")) {
    const fields = retention.querySelector(".fields");
    fields?.insertAdjacentHTML("beforeend", `<div><label for="s-meeting-audio-retention">Audio riunioni (giorni)</label><input id="s-meeting-audio-retention" name="meeting_audio_retention_days" type="number" min="0" max="3650"></div>`);
  }
}

function phase10Duration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map(value => String(value).padStart(2, "0")).join(":");
}

function phase10SetProgress(id, value) {
  const bar = $(id);
  if (!bar) return;
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  bar.setAttribute("aria-valuenow", String(Math.round(pct)));
  const fill = bar.querySelector("span");
  if (fill) fill.style.width = `${pct}%`;
}

function phase10MeetingStatus(value) {
  return ({
    recording: "Registrazione",
    finishing: "Chiusura registrazione",
    transcribing: "Trascrizione finale",
    downloading_diarization: "Download modelli diarizzazione",
    diarizing: "Diarizzazione",
    cancelling: "Annullamento",
    completed: "Completata",
    interrupted: "Interrotta · audio recuperato",
    cancelled: "Annullata",
    error: "Errore",
  })[String(value)] || label(value || "Idle");
}

function phase10RenderRuntime(runtime) {
  state.meetingRuntime = runtime || null;
  const active = runtime && !["completed", "error", "cancelled", "interrupted"].includes(String(runtime.status));
  $("meeting-start").disabled = !!active || state.live || state.file;
  $("meeting-finish").disabled = !runtime || runtime.status !== "recording";
  $("meeting-cancel").disabled = !active;
  $("meeting-status").textContent = runtime ? phase10MeetingStatus(runtime.status) : "Idle";
  $("meeting-model").textContent = runtime?.model ? (modelLabels[runtime.model] || runtime.model) : "—";
  $("meeting-language-value").textContent = runtime?.language || "—";
  setOrb("meeting-orb", !!active);
  phase10SetProgress("meeting-transcription-progress", runtime?.progress || 0);
  phase10SetProgress("meeting-diarization-progress", runtime?.diarization_progress || 0);
  if (runtime?.status === "recording") {
    phase10TimerBase = Number(runtime.duration_s) || 0;
    phase10TimerAnchor = Date.now();
  } else if (runtime) {
    phase10TimerBase = Number(runtime.duration_s) || phase10TimerBase;
    phase10TimerAnchor = 0;
    $("meeting-duration").textContent = phase10Duration(phase10TimerBase);
  } else {
    phase10TimerBase = 0;
    phase10TimerAnchor = 0;
    $("meeting-duration").textContent = "00:00:00";
  }
}

function phase10RenderMeetingDevices(items) {
  const select = $("meeting-device");
  if (!select) return;
  const current = select.value;
  select.innerHTML = '<option value="">Rilevamento automatico</option>';
  (Array.isArray(items) ? items : []).filter(device => !!device?.is_mic).forEach(device => {
    const option = document.createElement("option");
    option.value = device.name;
    option.textContent = device.name + (device.hostapi_name ? ` · ${device.hostapi_name}` : "");
    select.append(option);
  });
  if ([...select.options].some(option => option.value === current)) select.value = current;
}

function phase10RefreshMeetingDevices() {
  call("refreshDevices", ["microphone"], result => phase10RenderMeetingDevices(json(result)));
}

function phase10StartMeeting() {
  const language = $("meeting-language").value.trim() || state.boot?.settings?.language || "auto";
  const count = Math.max(0, Number($("meeting-speaker-count").value) || 0);
  call("startMeeting", [$("meeting-device").value, language, count], result => {
    const response = json(result);
    if (!response?.ok) {
      showError(response?.error || "Impossibile avviare la riunione", "meeting");
      return;
    }
    phase10RenderRuntime(response.meeting);
    notice("Registrazione riunione avviata");
  });
}

function phase10FinishMeeting() {
  call("finishMeeting", [], result => {
    const response = json(result);
    if (!response?.ok) {
      showError(response?.error || "Impossibile terminare la riunione", "meeting");
      return;
    }
    phase10RenderRuntime(response.meeting);
    notice("Chiusura registrazione in corso. L'analisi partirà automaticamente.");
  });
}

function phase10RefreshMeetingList() {
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
      const button = document.createElement("button");
      button.type = "button";
      button.className = "history-item";
      const when = item.started_at ? new Date(item.started_at).toLocaleString() : item.id;
      button.innerHTML = `<strong>${when}</strong><small>${phase10MeetingStatus(item.status)} · ${item.language || "auto"}</small><span>${item.text_preview || "Nessun testo"}</span>`;
      button.onclick = () => phase10LoadMeeting(item.id);
      list.append(button);
    });
  });
}

function phase10SpeakerLabel(id, names) {
  if (!id) return "Speaker ?";
  if (names?.[id]) return names[id];
  const tail = Number(String(id).split("_").pop());
  return Number.isFinite(tail) ? `Speaker ${tail + 1}` : id;
}

function phase10LoadMeeting(sessionId) {
  call("getMeetingSession", [sessionId], result => {
    const meeting = json(result);
    if (!meeting?.meeting) {
      showError("Dati riunione non disponibili", "meeting");
      return;
    }
    phase10Meeting = meeting;
    phase10RenderReview();
  });
}

function phase10RenderReview() {
  const meeting = phase10Meeting;
  const metadata = meeting?.meeting;
  if (!meeting || !metadata) return;
  $("meeting-review").hidden = false;
  $("meeting-review-title").textContent = meeting.started_at ? `Riunione · ${new Date(meeting.started_at).toLocaleString()}` : "Riunione";
  $("meeting-raw").textContent = meeting.text || "Nessun transcript raw.";

  const speakerIds = new Set();
  (metadata.diarization_segments || []).forEach(item => item.speaker_id && speakerIds.add(item.speaker_id));
  (metadata.review_segments || []).forEach(item => {
    if (item.speaker_id) speakerIds.add(item.speaker_id);
    (item.speaker_candidates || []).forEach(id => speakerIds.add(id));
  });
  const names = metadata.speaker_names || {};
  const speakerBox = $("meeting-speakers");
  speakerBox.replaceChildren();
  [...speakerIds].sort().forEach(id => {
    const row = document.createElement("label");
    row.className = "meeting-speaker-row";
    const caption = document.createElement("strong");
    caption.textContent = phase10SpeakerLabel(id, {});
    const input = document.createElement("input");
    input.type = "text";
    input.value = names[id] || "";
    input.placeholder = "Nome manuale";
    input.onchange = () => call("setMeetingSpeakerName", [meeting.id, id, input.value], responseRaw => {
      const response = json(responseRaw);
      if (response?.ok) {
        phase10Meeting = response.meeting;
        phase10RenderReview();
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
    const row = document.createElement("article");
    row.className = "meeting-review-segment" + (item.uncertain ? " meeting-uncertain" : "");
    const head = document.createElement("div");
    head.className = "meeting-review-head";
    const seek = document.createElement("button");
    seek.type = "button";
    seek.textContent = phase10Duration(item.start).replace(/^00:/, "");
    seek.onclick = () => {
      const audio = $("meeting-audio");
      if (audio?.src) audio.currentTime = Number(item.start) || 0;
    };
    const speaker = document.createElement("span");
    speaker.className = "meeting-review-speaker";
    speaker.textContent = phase10SpeakerLabel(item.speaker_id, names) + (item.uncertain ? " · incerto" : "");
    head.append(seek, speaker);
    const textarea = document.createElement("textarea");
    textarea.value = item.text || "";
    textarea.setAttribute("aria-label", `Testo segmento ${index + 1}`);
    const save = document.createElement("button");
    save.type = "button";
    save.textContent = "Salva correzione";
    save.onclick = () => call("editMeetingSegment", [meeting.id, index, textarea.value], raw => {
      const response = json(raw);
      if (response?.ok) {
        phase10Meeting = response.meeting;
        notice("Correzione salvata; il transcript raw è invariato");
      } else showError(response?.error || "Correzione non salvata", "meeting");
    });
    row.append(head, textarea, save);
    list.append(row);
  });

  call("getMeetingAudioUrl", [meeting.id], url => {
    const audio = $("meeting-audio");
    if (!audio) return;
    const value = String(url || "");
    if (value) audio.src = value;
    else audio.removeAttribute("src");
    audio.load();
    $("meeting-delete-audio").disabled = !value;
  });
}

function phase10ExportMeeting(fmt) {
  if (!phase10Meeting?.id) return;
  call("exportMeetingFormat", [phase10Meeting.id, fmt], raw => {
    const response = json(raw);
    if (response?.cancelled) return;
    if (!response?.ok) showError(response?.error || "Export riunione fallito", "meeting");
    else notice(`Riunione esportata: ${response.path}`);
  });
}

function phase10DeleteAudio() {
  if (!phase10Meeting?.id) return;
  call("deleteMeetingAudio", [phase10Meeting.id], raw => {
    const response = json(raw);
    if (!response?.ok) showError(response?.error || "Audio non eliminato", "meeting");
    else {
      notice("Audio eliminato; trascrizione e review sono state conservate");
      phase10LoadMeeting(phase10Meeting.id);
    }
  });
}

function phase10Bind() {
  phase10EnsureUI();
  const meetingNav = document.querySelector('.nav[data-view="meeting"]');
  if (meetingNav) meetingNav.onclick = () => {
    switchView("meeting");
    phase10RefreshMeetingDevices();
    phase10RefreshMeetingList();
  };
  $("meeting-refresh-devices").onclick = phase10RefreshMeetingDevices;
  $("meeting-refresh-list").onclick = phase10RefreshMeetingList;
  $("meeting-start").onclick = phase10StartMeeting;
  $("meeting-finish").onclick = phase10FinishMeeting;
  $("meeting-cancel").onclick = () => call("cancelMeeting", [], raw => phase10RenderRuntime(json(raw)?.meeting));
  $("meeting-export-txt").onclick = () => phase10ExportMeeting("txt");
  $("meeting-export-srt").onclick = () => phase10ExportMeeting("srt");
  $("meeting-export-vtt").onclick = () => phase10ExportMeeting("vtt");
  $("meeting-delete-audio").onclick = phase10DeleteAudio;
  if ($("live-start")) $("live-start").onclick = startLive;
}

const phase10LegacySourceUI = sourceUI;
sourceUI = function() {
  phase10LegacySourceUI();
  const row = $("live-recording-row");
  if (row) row.hidden = state.source !== "microphone";
  if (state.source !== "microphone" && $("live-recording")) $("live-recording").checked = false;
};

const phase10LegacyStartLive = startLive;
startLive = function() {
  const settings = state.boot?.settings || {};
  const input = selectedInputValue();
  if (state.file) {
    notice("Ferma la trascrizione file prima di aggiungere una sessione Live", true);
    return;
  }
  if (state.meetingRuntime && !["completed", "error", "cancelled", "interrupted"].includes(String(state.meetingRuntime.status))) {
    notice("Termina la riunione prima di aggiungere una sessione Live", true);
    return;
  }
  if (state.source === "application" && !input) {
    notice("Seleziona uno stream applicazione da trascrivere", true);
    return;
  }
  const record = state.source === "microphone" && !!$("live-recording")?.checked;
  if ($("live-status")) $("live-status").textContent = "Creazione sessione";
  call("startLiveWithRecording", [state.source, input, settings.language || "auto", record]);
};

const phase10LegacyShowHistorySession = showHistorySession;
showHistorySession = function(session) {
  phase10LegacyShowHistorySession(session);
  phase10HistoryMeetingId = session?.kind === "meeting" ? session.id : null;
  if ($("meeting-open-history")) $("meeting-open-history").hidden = !phase10HistoryMeetingId;
};

const phase10LegacyClearHistorySelection = clearHistorySelection;
clearHistorySelection = function() {
  phase10LegacyClearHistorySelection();
  phase10HistoryMeetingId = null;
  if ($("meeting-open-history")) $("meeting-open-history").hidden = true;
};

const phase10LegacyHydrate = hydrate;
hydrate = function(bootstrap) {
  phase10LegacyHydrate(bootstrap);
  phase10EnsureUI();
  if ($("meeting-language")) $("meeting-language").value = bootstrap.settings?.language || "auto";
  if ($("s-meeting-audio-retention")) $("s-meeting-audio-retention").value = bootstrap.settings?.meeting_audio_retention_days ?? 30;
  phase10RenderMeetingDevices(bootstrap.devices || []);
  phase10RenderRuntime(bootstrap.meetingRuntime || null);
  sourceUI();
};

const phase10LegacyEvent = event;
event = function(name, payload) {
  phase10LegacyEvent(name, payload);
  const value = json(payload);
  if (name === "meeting_started" || name === "meeting_updated") {
    phase10RenderRuntime(value);
  } else if (name === "meeting_completed") {
    phase10RefreshMeetingList();
    refreshHistory();
    phase10LoadMeeting(String(value));
    notice("Riunione pronta per la revisione");
  } else if (name === "meeting_error") {
    showError(value?.error || "Errore riunione", "meeting");
    phase10RefreshMeetingList();
  } else if (name === "meeting_review_changed") {
    if (phase10Meeting?.id === String(value)) phase10LoadMeeting(String(value));
  } else if (name === "microphone_recording_saved") {
    if (historyIsVisible()) refreshHistory();
  } else if (name === "meeting_model_progress") {
    $("meeting-model-note").textContent = `Download ${value?.model || "modello"}: ${Number(value?.percent) || 0}%`;
  } else if (name === "audio_devices_changed") {
    phase10RenderMeetingDevices(value);
  }
};

const phase10LegacyBind = bind;
bind = function() {
  phase10LegacyBind();
  phase10Bind();
};

setInterval(() => {
  if (!phase10TimerAnchor || state.meetingRuntime?.status !== "recording") return;
  const elapsed = (Date.now() - phase10TimerAnchor) / 1000;
  if ($("meeting-duration")) $("meeting-duration").textContent = phase10Duration(phase10TimerBase + elapsed);
}, 500);

function phase10LateInit() {
  phase10EnsureUI();
  phase10Bind();
  if (state.boot) hydrate(state.boot);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", phase10LateInit);
else phase10LateInit();