# System-wide Dictation

UltraTranscribr 5.5 adds a dedicated low-latency Dictation workflow for Linux desktops. It is intentionally separate from normal Live transcription: Live keeps its longer, loss-resistant segmentation while Dictation uses a rolling microphone window tuned for interactive text entry.

## Runtime architecture

The canonical flow is:

```text
XDG GlobalShortcuts
  -> DictationActivationService
  -> DictationService
  -> AudioCaptureThread (microphone, 16 kHz)
  -> DictationTranscriberThread
  -> PrioritizedWhisperBackend (INTERACTIVE)
  -> StablePrefixCommitter
  -> native Dictation integration
  -> temporary clipboard + XDG RemoteDesktop Shift+Insert
  -> currently focused field
```

Python owns activation state, capture, inference, stability, settings and lifecycle. Native Qt adapters own only XDG Portal integration, clipboard handling and the transient overlay. No arbitrary keyboard or filesystem operation is exposed to the QML layer.

## Activation modes

- `push_to_talk` (default): press and hold the registered global shortcut; release to finalize.
- `toggle`: first activation starts Dictation and the next activation stops it.

UltraTranscribr proposes `Meta+H` (`LOGO+h`) as the preferred trigger. The actual shortcut binding is owned by the desktop through `org.freedesktop.portal.GlobalShortcuts`; UltraTranscribr does not use `xdotool`, `pynput` or X11-only global hooks.

## Insertion modes

- `live` (default): words are inserted only after the stable-prefix algorithm has observed them consistently across consecutive Whisper hypotheses. The revisable tail remains internal preview state and is not injected yet; the transient overlay intentionally shows status only.
- `final`: no text is inserted during speech; the final committed transcript is pasted once Dictation drains. This is the safer mode for applications where progressive insertion is undesirable.

## Low-latency profile

Initial defaults are deliberately isolated from normal Live:

- microphone capture chunk: 250 ms;
- inference step: at least 750 ms of new audio; each request takes every chunk queued while the previous one ran, so the queue never grows while speaking;
- growing Whisper window: from the first word; from 25 s it is committed up to the last Whisper segment boundary (from the request's own timestamps) and restarted with the rest, or closed whole at 29 s if Whisper found no boundary;
- requests run only when the audio added since the previous one contains speech (two 100 ms frames above the silence threshold);
- minimum audio before inference: 1 s;
- request timeout: 60 s;
- prompt: the last 500 characters of earlier segments only (Whisper skips speech it already finds in the prompt, and the current segment is re-transcribed each time).

These values are benchmark starting points, not universal optimums. Use the validation tools before changing them globally.

## Shared inference scheduling

All Whisper requests are scheduled by one backend owner:

1. `INTERACTIVE` — Dictation;
2. `LIVE` — normal Live/meeting work;
3. `BATCH` — file transcription.

An active inference is never preempted. Waiting work ages upward after 30 seconds per priority level, preventing file work from starving indefinitely under sustained interactive traffic. Multiple `whisper-server` instances, when explicitly enabled, are resources of the same scheduler rather than independent policy islands.

Because the legacy HTTP backend can cancel an active request only by terminating the shared server, File Stop becomes non-destructive while Dictation is active: the File stop flag is set, an already-active HTTP request is allowed to return, and no following File chunk is submitted. Full application shutdown still terminates the backend deterministically after Dictation has been closed.

## Clipboard safety

System text insertion is a serialized transaction:

1. clone all current clipboard MIME formats;
2. put the dictation fragment on the clipboard with an UltraTranscribr transaction marker;
3. ask RemoteDesktop to inject `Shift+Insert`;
4. wait briefly for the target application to request the clipboard;
5. restore the original clipboard only if the marker is still present.

If the user copies something else before restoration, UltraTranscribr leaves the new clipboard untouched.

## Overlay

The Dictation overlay is a small non-focusable local QML window (`ui/qml/DictationOverlay.qml`) using the project dark-neumorphic palette; `ui/native/dictation_overlay.py` only controls its visibility and placement and exposes no application operations. The animated bars are a status animation, not an audio waveform.

## Diagnostics

Run the read-only desktop doctor from the project root:

```bash
.venv/bin/python tools/dictation_doctor.py
.venv/bin/python tools/dictation_doctor.py --json
```

It checks Wayland/KDE session hints, D-Bus, XDG Desktop Portal, KDE portal backend and the required GlobalShortcuts/RemoteDesktop interfaces. It does not grant permissions or modify the system.

Runtime metrics are appended as JSONL under the UltraTranscribr XDG data directory and can be summarized with:

```bash
.venv/bin/python tools/dictation_validation_report.py ~/.local/share/ultratranscribr/dictation-metrics.jsonl
```

See `docs/DICTATION_VALIDATION.md` for the final real-desktop campaign.

## Known validation boundary

The code can be unit-tested and statically validated without a desktop, but these points require a real CachyOS/KDE Wayland session and remain intentionally unclaimed until tested there:

- QtDBus marshalling of portal request/shortcut structures against the installed KDE portal version;
- permission prompts and session recovery;
- actual focused-field paste in Firefox/Chromium, LibreOffice, Konsole and IDEs;
- focus changes while speaking;
- end-to-end latency on the target GPU/model;
- clipboard timing under real applications.
