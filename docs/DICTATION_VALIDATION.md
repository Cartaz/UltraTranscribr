# Dictation validation campaign

Run this campaign only after installing the consolidated Phase 11 implementation on the target CachyOS/KDE Wayland system.

## 1. Environment

```bash
.venv/bin/python tools/dictation_doctor.py
```

Do not continue past a `FAIL`. A `WARN` is acceptable only when the warning is understood and unrelated to the capability under test.

## 2. Permission and lifecycle checks

1. Launch UltraTranscribr normally and leave it in the background.
2. Trigger Dictation for the first time and verify KDE presents the expected Global Shortcut and Remote Desktop keyboard permission flows.
3. Close the main window and confirm UltraTranscribr remains available in the tray.
4. Dictate while the main window is hidden.
5. Quit explicitly from the tray and confirm no `whisper-server` child remains.
6. Relaunch and verify portal permissions recover cleanly; if KDE asks again, record the portal/version behavior.

## 3. Cross-application matrix

Test both insertion modes (`live`, `final`) and both activation modes (`push_to_talk`, `toggle`) in each target:

| Target | Plain text | punctuation | accented/Unicode text | existing clipboard restored | focus preserved |
| --- | --- | --- | --- | --- | --- |
| Firefox text field | [ ] | [ ] | [ ] | [ ] | [ ] |
| Chromium/Chrome text field | [ ] | [ ] | [ ] | [ ] | [ ] |
| LibreOffice Writer | [ ] | [ ] | [ ] | [ ] | [ ] |
| Konsole shell prompt | [ ] | [ ] | [ ] | [ ] | [ ] |
| IDE/editor | [ ] | [ ] | [ ] | [ ] | [ ] |

For every target also test an empty field, insertion in the middle of existing text and repeated Dictation sessions without refocusing UltraTranscribr.

## 4. Focus and clipboard adversarial cases

- Start Dictation in application A, then move focus to application B before the first stable commit. Record which field receives the text; this defines actual compositor behavior.
- Copy unrelated content immediately after a Dictation paste and verify UltraTranscribr does not overwrite that newer clipboard content.
- Cancel/release before backend startup completes.
- Reactivate during finalization.
- Deny RemoteDesktop permission once, then retry.
- Revoke portal permission from KDE settings and verify the next Dictation attempt fails visibly and can recover after permission is granted again.

## 5. Concurrency

- Dictation while normal Live is active: Dictation should receive the next available inference slot without terminating Live.
- Dictation while File transcription is active: active File inference may finish, then Dictation should be scheduled first.
- Stop File during active Dictation: the shared whisper-server must not be killed; an already-active File HTTP request may finish before the worker reaches `stopped`.
- Repeat with `backend_instances=2` only if memory headroom is known to be sufficient.

## 6. Latency capture

Perform at least 20 short Dictation sessions with the selected production model. Then run:

```bash
.venv/bin/python tools/dictation_validation_report.py ~/.local/share/ultratranscribr/dictation-metrics.jsonl
```

Record median, p95 and maximum for:

- activation → listening;
- activation → first stable commit;
- activation → first observed insertion;
- finalization;
- maximum scheduler wait.

A missing `first insertion` sample is a failure/missing measurement and must remain `null`; do not replace it with zero.

## 7. Acceptance

Phase 11 real-desktop validation can be marked complete only when:

- all target applications accept text reliably;
- no focus theft is observed from the overlay/app window;
- clipboard preservation is confirmed;
- portal denial/recovery is understandable and recoverable;
- shared Live/File work does not corrupt Dictation state;
- shutdown leaves no owned child process;
- measured latency is recorded rather than estimated.
