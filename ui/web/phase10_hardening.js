"use strict";

function phase10IsBusy() {
  const runtime = state.meetingRuntime;
  return !!runtime && !["completed", "error", "cancelled", "interrupted"].includes(String(runtime.status));
}

const phase10GuardLegacySessionBusy = sessionBusy;
sessionBusy = function() {
  return phase10GuardLegacySessionBusy() || phase10IsBusy();
};

const phase10GuardLegacyRenderRuntime = phase10RenderRuntime;
phase10RenderRuntime = function(runtime) {
  phase10GuardLegacyRenderRuntime(runtime);
  lockSettings();
  renderModels(state.models);
  const meetingBusy = phase10IsBusy();
  if ($("file-start")) $("file-start").disabled = meetingBusy || state.live || state.file;
  if ($("file-pick")) $("file-pick").disabled = meetingBusy || state.live;
  if ($("live-start")) {
    const missingStream = state.source === "application" && !$("live-stream")?.value;
    $("live-start").disabled = meetingBusy || !!state.file || missingStream;
  }
};

// Replace the initial implementation with DOM-only rendering so transcript or
// source text can never be interpreted as HTML.
phase10RefreshMeetingList = function() {
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
      const title = document.createElement("strong");
      title.textContent = item.started_at ? new Date(item.started_at).toLocaleString() : String(item.id || "Riunione");
      const meta = document.createElement("small");
      meta.textContent = `${phase10MeetingStatus(item.status)} · ${item.language || "auto"}`;
      const preview = document.createElement("span");
      preview.textContent = item.text_preview || "Nessun testo";
      button.append(title, meta, preview);
      button.onclick = () => phase10LoadMeeting(item.id);
      list.append(button);
    });
  });
};

function phase10EnsureHistoryRecordingUI() {
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

function phase10FormatBytes(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function phase10ShowLiveRecording(session) {
  phase10EnsureHistoryRecordingUI();
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
    info.textContent = `${phase10Duration(recording.duration_s)} · ${phase10FormatBytes(recording.size_bytes)} · FLAC lossless`;
    audio.src = recording.url || "";
    audio.load();
    remove.onclick = () => call("deleteSessionRecording", [session.id], responseRaw => {
      const response = json(responseRaw);
      if (!response?.ok) {
        showError(response?.error || "Registrazione non eliminata", "history");
        return;
      }
      notice("Registrazione eliminata; la trascrizione è stata conservata");
      phase10ShowLiveRecording(session);
    });
  });
}

const phase10GuardLegacyShowHistorySession = showHistorySession;
showHistorySession = function(session) {
  phase10GuardLegacyShowHistorySession(session);
  phase10ShowLiveRecording(session);
};

const phase10GuardLegacyClearHistorySelection = clearHistorySelection;
clearHistorySelection = function() {
  phase10GuardLegacyClearHistorySelection();
  phase10ShowLiveRecording(null);
};

phase10EnsureHistoryRecordingUI();
if (state.boot) phase10RenderRuntime(state.meetingRuntime);
