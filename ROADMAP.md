# UltraTranscribr Roadmap

This roadmap is the implementation checklist for the next development cycle. Items are ordered to reduce data-loss risk first, then improve usability and finally expand the audio/session architecture.

Legend: `[ ]` planned · `[~]` in progress · `[x]` completed

## Phase 1 — Never lose a transcription

### 1.1 Persistent transcription history
- [x] Add an XDG-compliant user data directory for saved transcription sessions.
- [x] Persist Live and File sessions independently from the web UI state.
- [x] Autosave text incrementally as backend events arrive.
- [x] Record metadata: kind, start/update/end time, status, source/file, model and language.
- [x] Add a History view to browse recent sessions and reopen their text.
- [x] Export a saved session to `.txt`.
- [x] Add delete/retention controls for saved sessions.
- [ ] Add optional session naming.

### 1.2 Recovery audio made visible
- [x] Emit an explicit event whenever untranscribed live audio is saved.
- [x] List recovery WAV files in the History view.
- [x] One-click retranscription of a recovery WAV.
- [x] Delete individual recovery files from the UI.
- [x] Clearly distinguish recoverable audio from normal transcript history.

### 1.3 Regression coverage
- [x] Unit-test session persistence, atomic writes and recovery discovery.
- [x] Add full lifecycle tests for Live autosave and File autosave.
- [x] Add UI contract tests for History/recovery actions.

## Phase 2 — Model management and clearer runtime state

### 2.1 Model manager UI
- [x] Show only supported UI models: Large v3, Large v3 Turbo, Medium.
- [ ] Show Installed / Not installed and size on disk.
- [ ] Add Download and Delete actions.
- [ ] Surface real download progress and download errors.
- [x] Keep resumable `.part` downloads and hash validation.
- [ ] Optional preload-on-start setting.

### 2.2 Runtime status
- [ ] Make backend/model loading states explicit without modal dialogs.
- [ ] Show current model, language and active input in one compact session summary.
- [ ] Improve actionable errors for missing audio source, backend startup and model downloads.

## Phase 3 — Generalize audio capture beyond Firefox

### 3.1 System audio
- [ ] Replace the Firefox-specific concept with a generic `system` playback source.
- [ ] Detect the default output monitor reliably on PipeWire/PulseAudio.
- [ ] Keep Microphone as a separate source.
- [ ] Preserve an explicit device selector for advanced users.
- [ ] Migrate existing `firefox` settings to `system` without losing configuration.

### 3.2 Per-application / per-stream capture
- [ ] Enumerate active playback streams with application/process metadata.
- [ ] Present application name, media title when available, PID/binary and current sink.
- [ ] Build a PipeWire/PulseAudio routing abstraction rather than hard-code browser names.
- [ ] Prototype isolated capture by routing a selected playback stream through a dedicated virtual/null sink and recording its monitor.
- [ ] Restore the original stream route when capture stops or the app exits.
- [ ] Handle streams that disappear/reappear and applications with multiple simultaneous streams.
- [ ] Add cleanup/recovery for virtual sinks left behind after a crash.

Technical note: PipeWire exposes playback streams as nodes and its PulseAudio compatibility layer supports built-in virtual/null sinks. This makes isolated per-stream capture feasible, but it requires controlled routing and cleanup rather than merely reading the default output monitor.

## Phase 4 — Multiple simultaneous transcription sessions

This phase intentionally comes after per-stream capture because the current controller owns one Live worker, one shared Whisper backend and one File worker.

- [ ] Introduce a runtime `TranscriptionSession` model with unique session IDs.
- [ ] Replace singleton Live state in `AppController` with a session manager.
- [ ] Give each live session its own audio capture, buffer, transcript journal and status.
- [ ] Define backend scheduling policy for multiple sessions.
- [ ] First implementation: serialize inference requests through one whisper-server while capturing all streams concurrently.
- [ ] Measure queue latency and expose it in the UI.
- [ ] Optional later experiment: multiple whisper-server instances only where hardware/RAM permits.
- [ ] UI for two or more independent live transcript cards.
- [ ] Stop/drain/recover each session independently.
- [ ] Stress tests for two simultaneous audio sources and shutdown during queued inference.

## Phase 5 — Audio source UX and diagnostics

- [ ] Refresh device/stream lists automatically when opening the Live view.
- [ ] Add a manual Refresh button.
- [ ] Show `available`, `playing`, `disconnected` state for selected sources.
- [ ] Replace generic sink errors with actionable guidance.
- [ ] Extend diagnostics with active playback streams, sinks, monitor sources and routing state.

## Phase 6 — Settings cleanup

- [ ] Split normal settings from Advanced settings.
- [ ] Keep model, language, source and VAD in the normal section.
- [ ] Move beam size, chunk size, forced sink, server port, GPU layers and compute type to Advanced.
- [ ] Consider removing manual window width/height fields and persist the last window geometry automatically, always respecting the 1200×800 minimum.
- [ ] Add reset-to-defaults per section rather than one global destructive reset.

## Phase 7 — Test hardening

- [ ] Dedicated `TranscriberThread` retry/drain/recovery tests.
- [ ] Dedicated `FileTranscriberThread` conversion/cancel/retry tests.
- [ ] `WhisperBackend` endpoint fallback, timeout and process lifecycle tests.
- [ ] Sink/stream discovery parser tests using captured pactl/PipeWire fixtures.
- [ ] WebChannel bridge integration tests.
- [ ] Race tests for rapid Start/Stop/Start and app shutdown.
- [ ] Multi-session tests before enabling concurrent sessions by default.

## Phase 8 — Installer, logs and documentation

- [ ] Make `install.sh` fully idempotent and skip unchanged expensive build steps.
- [ ] Add a final environment self-check: oneAPI, Level Zero, Intel GPU, whisper-server, ffmpeg, models, optional Demucs.
- [ ] Rotate application logs instead of allowing unbounded growth.
- [ ] Replace the placeholder README with complete installation, usage and troubleshooting documentation.
- [ ] Document supported CachyOS/Arch environment and optional components.

## Phase 9 — Power-user features

Only after the safety/session architecture is stable:

- [ ] Batch file queue.
- [ ] Drag-and-drop multiple files.
- [ ] Timestamp-preserving transcription output.
- [ ] `.srt` / `.vtt` export.
- [ ] Search across transcription history.
- [ ] Optional transcript post-processing profiles that never overwrite the original raw transcript.
