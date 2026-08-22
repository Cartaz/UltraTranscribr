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
- [x] Show Installed / Not installed and size on disk.
- [x] Add Download and Delete actions.
- [x] Surface real download progress and download errors.
- [x] Keep resumable `.part` downloads and hash validation.
- [ ] Optional preload-on-start setting.

### 2.2 Runtime status
- [x] Make backend/model loading states explicit without modal dialogs.
- [x] Show current model, language and active input in one compact session summary.
- [x] Improve actionable errors for missing audio source, backend startup and model downloads.

## Phase 3 — Generalize audio capture beyond Firefox

### 3.1 System audio
- [x] Replace the Firefox-specific concept with a generic `system` playback source.
- [x] Detect the default output monitor reliably on PipeWire/PulseAudio.
- [x] Keep Microphone as a separate source.
- [x] Preserve an explicit device selector for advanced users.
- [x] Migrate existing `firefox` settings to `system` without losing configuration.

### 3.2 Per-application / per-stream capture
- [x] Enumerate active playback streams with application/process metadata.
- [x] Present application name, media title when available, PID/binary and current sink.
- [x] Build a PipeWire/PulseAudio routing abstraction rather than hard-code browser names.
- [x] Prototype isolated capture by routing a selected playback stream through a dedicated virtual/null sink and recording its monitor.
- [x] Restore the original stream route when capture stops or the app exits.
- [x] Handle streams that disappear/reappear and applications with multiple simultaneous streams.
- [x] Add cleanup/recovery for virtual sinks left behind after a crash.

Technical note: PipeWire exposes playback streams as nodes and its PulseAudio compatibility layer supports built-in virtual/null sinks. This makes isolated per-stream capture feasible, but it requires controlled routing and cleanup rather than merely reading the default output monitor.

## Phase 4 — Multiple simultaneous transcription sessions

The first multi-session architecture keeps one shared whisper-server while capture, buffering, routing, persistence and UI state are isolated per Live session.

- [x] Introduce a runtime `TranscriptionSession` model with unique session IDs.
- [x] Replace singleton Live state in `AppController` with a session manager.
- [x] Give each live session its own audio capture, buffer, transcript journal and status.
- [x] Define backend scheduling policy for multiple sessions.
- [x] First implementation: serialize inference requests through one whisper-server while capturing all streams concurrently.
- [x] Measure queue latency and expose it in the UI.
- [ ] Optional later experiment: multiple whisper-server instances only where hardware/RAM permits.
- [x] UI for two or more independent live transcript cards.
- [x] Stop/drain/recover each session independently.
- [x] Stress tests for two simultaneous audio sources and shutdown during queued inference.

## Phase 5 — Audio source UX and diagnostics

- [x] Refresh device/stream lists automatically when opening the Live view.
- [x] Add a manual Refresh button.
- [x] Show `available`, `playing`, `disconnected` state for selected sources.
- [x] Replace generic sink errors with actionable guidance.
- [x] Extend diagnostics with active playback streams, sinks, monitor sources and routing state.

## Phase 6 — Settings cleanup

- [x] Split normal settings from Advanced settings.
- [x] Keep model, language, source and VAD in the normal section.
- [x] Move beam size, chunk size, forced sink, server port, GPU layers and compute type to Advanced.
- [x] Remove manual window width/height fields and persist the last window geometry automatically, always respecting the 1200×800 minimum.
- [x] Add reset-to-defaults per section rather than one global destructive reset.

## Phase 7 — Test hardening

- [x] Dedicated `TranscriberThread` retry/drain/recovery tests.
- [x] Dedicated `FileTranscriberThread` conversion/cancel/retry tests.
- [x] `WhisperBackend` endpoint fallback, timeout and process lifecycle tests.
- [x] Sink/stream discovery parser tests using captured pactl/PipeWire fixtures.
- [x] WebChannel bridge integration tests.
- [x] Race tests for rapid Start/Stop/Start and app shutdown.
- [x] Multi-session tests before enabling concurrent sessions by default.

## Phase 8 — Installer, logs and documentation

- [x] Make `install.sh` fully idempotent and skip unchanged expensive build steps.
- [x] Add a final environment self-check: oneAPI, Level Zero, Intel GPU, whisper-server, ffmpeg, models, optional Demucs.
- [x] Rotate application logs instead of allowing unbounded growth.
- [x] Replace the placeholder README with complete installation, usage and troubleshooting documentation.
- [x] Document supported CachyOS/Arch environment and optional components.

## Phase 9 — Power-user features

Only after the safety/session architecture is stable:

- [x] Batch file queue.
- [x] Drag-and-drop multiple files.
- [x] Timestamp-preserving transcription output.
- [x] `.srt` / `.vtt` export.
- [x] Search across transcription history.
- [x] Optional transcript post-processing profiles that never overwrite the original raw transcript.

## Phase 10 — Meeting recording, diarization and review

**Live → Microphone** keeps its lightweight transcription behavior by default. A per-session **Salva registrazione** toggle is available only for microphone Live sessions and defaults to OFF. The dedicated **Riunione** workflow always records the microphone and uses the retained audio for final transcription, diarization and later review.

### 10.0 Shared microphone recording
- [x] Add one shared PCM16→FLAC recorder used by both Live Microphone and Riunione.
- [x] Add a per-session Live Microphone `Salva registrazione` toggle, default OFF.
- [x] Keep Audio di sistema and Applicazione behavior unchanged.
- [x] Journal microphone PCM progressively and recover interrupted journals without blocking GUI startup.
- [x] Allow retained Live microphone audio to be played/deleted independently from its transcript.

### 10.1 Meeting capture and persistence
- [x] Add a dedicated `meeting` session type and Riunione tab.
- [x] Record the selected microphone for the whole meeting.
- [x] Store microphone audio progressively in a crash-resistant journal and finalize to lossless FLAC mono 16 kHz.
- [x] Keep recording metadata, duration, audio path and processing status with the meeting session.
- [x] Allow deleting only the retained audio while preserving the transcript.
- [x] Add an audio-retention setting independent from transcript-history retention.

### 10.2 Post-meeting transcription and diarization
- [x] Produce a timestamp-preserving final transcription from the complete recording.
- [x] Run fully local speaker diarization after recording and persist stable speaker IDs such as `SPEAKER_00`.
- [x] Align diarization intervals with transcript segments without overwriting raw Whisper output.
- [x] Support overlapping/uncertain speaker regions explicitly rather than inventing an identity.

### 10.3 Manual review UI
- [x] Show detected speakers as `Speaker 1`, `Speaker 2`, etc. until manually named.
- [x] Let the user assign or change a display name for each speaker and propagate it through the rendered transcript.
- [x] Persist speaker-name mappings separately from diarization results.
- [x] Add an audio player with seek controls in the meeting review view.
- [x] Clicking a transcript intervention seeks the player to that timestamp.
- [x] Allow manual correction of transcription text during review while retaining the original raw transcript separately.

### 10.4 Meeting export and regression coverage
- [x] Export reviewed meetings as speaker-aware `.txt`, `.srt` and `.vtt`.
- [x] Fall back to `Speaker N` wherever no manual name has been assigned.
- [x] Test crash recovery, long-recording streaming behavior, diarization alignment, speaker renaming, manual transcript edits, audio deletion/retention and exports.
