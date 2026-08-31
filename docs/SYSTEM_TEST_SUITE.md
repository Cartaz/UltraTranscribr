# UltraTranscribr — System Test Suite

Suite di collaudo manuale end-to-end per il sistema reale di riferimento **CachyOS/Arch + KDE Plasma + Wayland**.

Questa suite integra i test automatici e `docs/DICTATION_VALIDATION.md`. Non sostituisce `pytest`: serve a verificare ciò che CI/offscreen non può provare realmente, in particolare hardware audio/GPU, PipeWire, XDG Portal, focus, clipboard, applicazioni esterne, latenza e lifecycle dei processi.

## Convenzioni

Priorità:

- **P0** — requisito bloccante: un fallimento impedisce di considerare la build pronta.
- **P1** — funzionalità principale o regressione importante.
- **P2** — stress, compatibilità estesa o edge case.

Esito consigliato per ogni test:

- `[x] PASS`
- `[ ] FAIL`
- `[ ] SKIP` con motivazione nelle note

Quando un test fallisce, annotare almeno:

- ID del test;
- comportamento osservato;
- comportamento atteso;
- eventuale messaggio UI;
- ultime righe di `~/.config/ultratranscribr/ultratranscribr.log`;
- applicazione coinvolta e versione, quando rilevante.

---

# 0. Scheda ambiente

Compilare prima di iniziare.

```text
Data test:
Commit Git:
Versione UltraTranscribr:
CachyOS/Arch:
Kernel:
KDE Plasma:
Wayland/X11:
PipeWire:
Python:
PySide6:
GPU Intel:
Driver/Compute Runtime:
whisper.cpp commit:
Modello principale:
Microfono:
Output audio:
Browser Firefox:
Browser Chromium/Chrome:
Editor/IDE:
```

Comandi utili:

```bash
git rev-parse HEAD
uname -a
python --version
plasmashell --version
pactl info
wpctl status
```

---

# 1. Baseline automatica

## SYS-001 — Repository pulita e commit corretto — P0

**Procedura**

```bash
git status --short
git rev-parse HEAD
```

**Atteso**

- working tree pulito prima del collaudo;
- HEAD corrisponde al commit che si intende testare.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-002 — Compileall — P0

```bash
.venv/bin/python -m compileall -q main.py config core ui tests
```

**Atteso**: exit code `0`, nessun traceback.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-003 — Suite pytest completa — P0

```bash
.venv/bin/python -m pytest
```

**Atteso**: tutti i test passano.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-004 — Sintassi frontend — P0

```bash
node --check ui/web/app.js
node --check ui/web/multi_live.js
node --check ui/web/settings_cleanup.js
node --check ui/web/file_history.js
node --check ui/web/meeting.js
```

**Atteso**: tutti i comandi terminano con exit code `0`.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-005 — Sintassi installer — P0

```bash
bash -n install.sh
```

**Atteso**: exit code `0`.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 2. Installazione e ambiente

## SYS-010 — Installazione canonica da repository — P0

**Procedura**

```bash
chmod +x install.sh
./install.sh
```

**Atteso**

- nessun crash;
- `.venv` valida;
- dipendenze Python presenti;
- `whisper-server` disponibile;
- librerie SYCL presenti;
- modello predefinito e VAD disponibili;
- launcher desktop creato;
- self-check finale verde.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-011 — Installer idempotente — P1

**Procedura**: rieseguire immediatamente `./install.sh`.

**Atteso**

- nessuna reinstallazione/build costosa non necessaria;
- l'installer riconosce dipendenze/build già valide;
- applicazione ancora avviabile.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-012 — Environment check — P0

```bash
source /opt/intel/oneapi/setvars.sh
.venv/bin/python -m core.environment_check
```

**Atteso**: nessun requisito obbligatorio in stato FAIL.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-013 — Dictation Doctor — P0

```bash
.venv/bin/python tools/dictation_doctor.py
```

**Atteso**

- Wayland: OK;
- D-Bus sessione: OK;
- Portal Desktop: OK;
- GlobalShortcuts: OK;
- RemoteDesktop: OK;
- NotifyKeyboardKeysym disponibile;
- eventuali WARN sono compresi e non bloccanti.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 3. Avvio, finestra, tray e shutdown

## SYS-020 — Avvio canonico — P0

```bash
.venv/bin/python main.py
```

**Atteso**

- finestra principale visibile;
- nessun traceback;
- nessun freeze;
- dimensione non inferiore a 1200×800;
- UI caricata completamente.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-021 — Geometria finestra persistente — P1

**Procedura**

1. Ridimensionare/spostare la finestra.
2. Chiudere esplicitamente dal tray.
3. Riavviare.

**Atteso**: geometria precedente ripristinata nei limiti consentiti.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-022 — Close-to-tray — P0

**Procedura**: chiudere la finestra con il pulsante della window decoration.

**Atteso**

- processo resta vivo;
- icona tray resta disponibile;
- nessun `whisper-server` viene terminato solo per la chiusura della finestra.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-023 — Riapertura dal tray — P0

**Procedura**: usare `Mostra` dal tray dopo SYS-022.

**Atteso**: finestra torna visibile e utilizzabile senza nuova istanza dell'app.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-024 — Quit deterministico — P0

**Procedura**: usare `Esci` dal tray.

**Atteso**

- processo UltraTranscribr termina;
- nessun processo `whisper-server` posseduto resta orfano;
- nessun routing/null sink temporaneo posseduto resta attivo.

Controlli suggeriti:

```bash
pgrep -af whisper-server
pactl list short sinks
```

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 4. Impostazioni e model manager

## SYS-030 — Persistenza impostazioni — P1

**Procedura**

1. Cambiare lingua, modello e alcune opzioni non distruttive.
2. Chiudere dal tray.
3. Riavviare.

**Atteso**: valori validi ripristinati correttamente.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-031 — Config malformata — P0

**Preparazione**: fare una copia di backup di `~/.config/ultratranscribr/settings.json`.

**Procedura**

1. Chiudere UltraTranscribr.
2. Rendere temporaneamente il JSON non valido.
3. Avviare.

**Atteso**

- nessun crash;
- fallback ai default/valori validi;
- errore diagnostico nei log.

Ripristinare poi il backup.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-032 — Reset per sezione — P1

**Procedura**: modificare valori in una sezione e usare il relativo reset.

**Atteso**: si resetta soltanto la sezione richiesta; le altre restano invariate.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-033 — Download modello — P1

**Procedura**: scaricare un modello supportato non ancora installato.

**Atteso**

- progress reale;
- UI responsiva;
- file finale valido;
- stato `Installed` al termine.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-034 — Download interrotto/ripreso — P2

**Procedura**: interrompere l'app o la rete durante un download e riprovare.

**Atteso**: `.part` riutilizzato/ripreso senza corrompere il modello finale.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-035 — Eliminazione modello non in uso — P1

**Atteso**: eliminazione riuscita, UI aggiornata, nessun altro modello coinvolto.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-036 — Operazione distruttiva durante workflow incompatibile — P0

**Procedura**: durante una sessione che deve possedere il backend, tentare cambio/eliminazione modello o operazione incompatibile.

**Atteso**: operazione rifiutata chiaramente; sessione corrente non corrotta.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 5. Dettatura globale — Portal e lifecycle

Per i test dettagliati usare anche `docs/DICTATION_VALIDATION.md`.

## SYS-100 — Primo consenso GlobalShortcuts — P0

**Procedura**: avviare l'app in una sessione KDE Wayland pulita e completare il flusso permessi.

**Atteso**

- dialogo/flow KDE comprensibile;
- hotkey registrabile;
- nessun crash;
- attivazione successiva ricevuta dall'app.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-101 — Primo consenso RemoteDesktop keyboard-only — P0

**Atteso**

- permesso RemoteDesktop richiesto;
- accesso limitato alla tastiera;
- nessuna richiesta pointer/touchscreen non necessaria.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-102 — Restore permessi dopo riavvio — P1

**Procedura**: concedere il permesso, chiudere correttamente, riavviare.

**Atteso**: restore token gestito correttamente; nessun loop di richieste permesso.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-103 — Permesso negato — P0

**Procedura**: negare RemoteDesktop una volta.

**Atteso**

- errore visibile/diagnosticabile;
- app resta utilizzabile;
- nessun loop infinito;
- è possibile riprovare successivamente.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-104 — Permesso revocato — P1

**Procedura**: dopo un test funzionante revocare il permesso dalle impostazioni KDE e ritentare.

**Atteso**: fallimento controllato e recovery possibile dopo nuova concessione.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-105 — Dettatura con finestra nascosta — P0

**Procedura**: nascondere UltraTranscribr nel tray, focalizzare un'altra applicazione e dettare.

**Atteso**: funziona senza riaprire/focalizzare UltraTranscribr.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 6. Dettatura — modalità di attivazione

## SYS-110 — Push-to-talk base — P0

**Procedura**

1. Focalizzare un campo vuoto.
2. Tenere premuta la hotkey.
3. Pronunciare una frase.
4. Rilasciare.

**Atteso**

- stato `starting → listening → finalizing → idle` coerente;
- nessuna attivazione doppia;
- testo corretto nel target.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-111 — Push-to-talk molto breve — P1

**Procedura**: premere/rilasciare rapidamente senza parlare.

**Atteso**: nessun crash, nessun testo spurio, ritorno a idle.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-112 — Release durante startup backend — P1

**Procedura**: attivare e rilasciare immediatamente quando backend/modello non è ancora pronto.

**Atteso**: startup stale non avvia una sessione dopo il rilascio.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-113 — Toggle base — P0

**Procedura**: prima pressione avvia, seconda termina.

**Atteso**: una sola sessione, transizioni corrette, testo inserito.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-114 — Press ripetuta/autorepeat — P1

**Procedura**: mantenere premuta la hotkey abbastanza da generare eventuale key repeat.

**Atteso**: nessuna attivazione multipla o toggle involontario.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-115 — Cambio modalità tra sessioni — P1

**Procedura**: completare una sessione push-to-talk, passare a toggle, avviarne una nuova.

**Atteso**: la nuova policy si applica soltanto alla nuova sessione senza stato residuo.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 7. Dettatura — inserimento Live e Final

## SYS-120 — Live insertion — P0

**Atteso**

- vengono inseriti solo delta stabili;
- parole già inserite non vengono riscritte casualmente;
- spaziatura tra delta naturale;
- punteggiatura non riceve uno spazio spurio prima del segno.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-121 — Final insertion — P0

**Atteso**: nessun testo durante la dettatura; un solo inserimento finale al termine.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-122 — Italiano con accenti — P0

Dettare una frase contenente ad esempio `perché`, `più`, `è`, apostrofi e punteggiatura.

**Atteso**: Unicode corretto nel campo target.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-123 — Testo lungo — P1

Dettare per almeno 30–60 secondi.

**Atteso**

- nessun freeze;
- nessuna duplicazione massiva;
- rolling window stabile;
- finalizzazione completata.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-124 — Pausa nel parlato — P1

Inserire 3–5 secondi di silenzio a metà frase.

**Atteso**: nessun testo casuale dal silenzio; sessione resta coerente.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-125 — Riattivazione durante finalizzazione — P0

**Procedura**: terminare una dettatura e riattivare immediatamente.

**Atteso**

- la nuova sessione non riceve testo/callback della precedente;
- nessun delta perso;
- nessun evento stale nella telemetria.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 8. Dettatura — matrice cross-application

Eseguire **Live + Final** e almeno una volta **Push-to-talk + Toggle** per ogni target.

| ID | Target | Campo vuoto | Testo esistente | Inserimento nel mezzo | Unicode | Punteggiatura | Clipboard | Focus | Esito |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SYS-130 | Firefox | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| SYS-131 | Chromium/Chrome | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| SYS-132 | LibreOffice Writer | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| SYS-133 | Konsole | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| SYS-134 | Editor/IDE | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

**Atteso comune**

- `Shift+Insert` produce il paste previsto;
- overlay non prende focus;
- UltraTranscribr non appare davanti al target;
- testo finisce nel controllo che possiede il focus al momento del paste.

---

# 9. Dettatura — clipboard e focus avversi

## SYS-140 — Clipboard semplice preservata — P0

**Procedura**: copiare una stringa nota, dettare, poi incollare manualmente altrove.

**Atteso**: la stringa originale è ancora nel clipboard.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-141 — Clipboard MIME non testuale — P1

**Procedura**: copiare un'immagine o altro contenuto MIME, dettare, poi incollare dove supportato.

**Atteso**: contenuto MIME precedente ripristinato.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-142 — L'utente cambia clipboard durante il paste — P0

**Procedura**: subito dopo un inserimento Dictation, copiare rapidamente un nuovo contenuto.

**Atteso**: UltraTranscribr non sovrascrive il clipboard più recente dell'utente.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-143 — Cambio focus A → B prima del commit — P1

**Procedura**: avviare in applicazione A e spostare focus a B prima del primo inserimento.

**Atteso**: annotare il comportamento reale del compositor; nessun focus forzato da UltraTranscribr.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-144 — Overlay non-focusable — P0

**Atteso**: comparsa/aggiornamento/scomparsa overlay non modifica il focus corrente.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 10. Live — microfono

## SYS-200 — Live Microfono base — P0

**Procedura**: avviare Live con microfono e parlare per almeno 30 secondi.

**Atteso**

- cattura attiva;
- testo progressivo;
- UI responsiva;
- Stop termina in modo controllato.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-201 — Drain Live — P0

**Procedura**: parlare, poi usare Drain con audio ancora nel buffer.

**Atteso**: cattura termina; audio già accodato viene trascritto prima della chiusura.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-202 — Registrazione Live Microfono OFF — P1

**Atteso**: nessun FLAC permanente creato per la sessione.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-203 — Registrazione Live Microfono ON — P1

**Atteso**

- registrazione FLAC disponibile in cronologia;
- riproducibile;
- eliminabile senza eliminare transcript.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 11. Live — audio di sistema

## SYS-210 — Cattura output predefinito — P0

Riprodurre audio noto e avviare Live `Audio di sistema`.

**Atteso**: audio monitor corretto, trascrizione ricevuta, nessun input microfono mischiato.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-211 — Cambio output audio — P1

**Procedura**: cambiare output predefinito tra due dispositivi durante/tra sessioni secondo comportamento supportato.

**Atteso**: sorgente/errore aggiornati in modo comprensibile; nessun crash.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-212 — Nessun monitor disponibile — P1

**Atteso**: errore azionabile, non generico; app resta utilizzabile.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 12. Live — singola applicazione/stream

## SYS-220 — Enumerazione stream — P0

**Preparazione**: riprodurre audio simultaneo da almeno due applicazioni.

**Atteso**: elenco mostra stream distinti con metadata utili.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-221 — Isolamento applicazione A — P0

**Procedura**: selezionare solo A mentre A e B riproducono audio.

**Atteso**: transcript contiene A, non B.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-222 — Routing ripristinato dopo Stop — P0

**Atteso**: stream torna al sink originale; null sink temporaneo rimosso quando non più necessario.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-223 — Applicazione target termina durante capture — P1

**Atteso**: stato `disconnected`/errore controllato; nessun routing residuo.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-224 — Stream scompare e ricompare — P2

**Atteso**: comportamento coerente con la policy di reconnessione; nessun leak di sink/routing.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 13. Multi-sessione Live

## SYS-230 — Due Live contemporanee — P0

Avviare due sorgenti realmente distinte.

**Atteso**

- entrambe catturano senza bloccare la GUI;
- transcript separati;
- nessuna contaminazione di stato/session ID.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-231 — Stop indipendente — P0

Fermare una delle due sessioni.

**Atteso**: l'altra continua normalmente.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-232 — Queue latency visibile — P1

**Atteso**: eventuale attesa inferenza condivisa viene misurata/esposta senza bloccare capture.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-233 — Backend instances = 2 — P2

Eseguire solo con RAM/VRAM sufficiente.

**Atteso**: due capacità backend utilizzabili senza processi orfani o porte in conflitto.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 14. Scheduling Dictation / Live / File

## SYS-240 — Dictation durante Live — P0

**Atteso**

- richiesta Live attiva non viene preemptata;
- Dictation riceve il prossimo slot disponibile prima del successivo lavoro Live accodato;
- Live non viene terminata.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-241 — Dictation durante File — P0

**Atteso**

- chunk File già attivo può finire;
- Dictation passa davanti ai successivi chunk File;
- File riprende dopo.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-242 — Stop File durante Dictation — P0

**Atteso**: il shared `whisper-server` non viene terminato; Dictation resta funzionante.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-243 — Aging anti-starvation — P2

Creare carico interattivo/live prolungato insieme a File.

**Atteso**: il lavoro File non resta indefinitamente bloccato.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 15. File transcription e batch

## SYS-300 — File audio singolo — P0

**Atteso**: progress reale, testo finale completo, sessione salvata in cronologia.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-301 — File video via ffmpeg — P0

**Atteso**: conversione/transcription riuscita senza bloccare UI.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-302 — Batch multiplo FIFO — P0

Aggiungere almeno tre file.

**Atteso**: ordine coda coerente, avanzamento per file, risultati separati.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-303 — Drag-and-drop multiplo — P1

**Atteso**: file validi aggiunti una sola volta; nessun duplicato spurio.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-304 — Cancella file corrente — P0

**Atteso**: worker termina in modo controllato; batch può proseguire; backend non resta corrotto.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-305 — File non valido/corrotto — P0

**Atteso**: errore per quel file, nessun crash globale, coda restante utilizzabile.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-306 — Export TXT/SRT/VTT — P1

Usare un file con timestamp disponibili.

**Atteso**: formati validi e contenuto coerente col transcript.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-307 — Modalità Musica — P2

Solo se Demucs è installato.

**Atteso**: isolamento vocale e transcription senza interferire con modalità normali.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 16. Riunione

## SYS-400 — Avvio Riunione — P0

**Atteso**: registrazione microfono parte subito; stato meeting persistito.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-401 — Mutua esclusione — P0

Durante Riunione tentare Live, File e Dictation.

**Atteso**: operazioni incompatibili rifiutate senza interrompere la Riunione.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-402 — Registrazione lunga — P1

Registrare almeno 15–30 minuti se possibile.

**Atteso**

- RAM non cresce proporzionalmente all'intera registrazione;
- journal continua a essere scritto;
- UI resta reattiva.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-403 — Termina e finalizza FLAC — P0

**Atteso**: FLAC lossless valido, durata plausibile, nessun journal temporaneo improprio lasciato dopo successo.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-404 — Trascrizione finale timestampata — P0

**Atteso**: segmenti e timestamp coerenti con l'audio completo.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-405 — Diarizzazione — P0

Usare almeno due speaker distinguibili.

**Atteso**

- speaker tecnici stabili;
- nessuna identità inventata;
- regioni incerte/overlap gestite esplicitamente.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-406 — Numero speaker noto — P1

**Atteso**: impostazione rispettata dal processamento nei limiti del modello.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-407 — Rename speaker — P0

**Atteso**: nome visuale propagato nel render, mapping persistente separato dai dati diarizzazione.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-408 — Correzione manuale transcript — P0

**Atteso**: testo revisionato cambia; raw Whisper originale resta preservato.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-409 — Seek player da intervento — P1

**Atteso**: click su intervento sposta il player al timestamp corretto.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-410 — Export speaker-aware — P0

Provare `.txt`, `.srt`, `.vtt`.

**Atteso**: nomi speaker manuali usati quando disponibili, fallback `Speaker N` altrimenti.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-411 — Elimina solo audio Riunione — P1

**Atteso**: transcript/review preservati; registrazione rimossa.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 17. Cronologia, recovery e persistenza

## SYS-500 — Autosave Live — P0

**Procedura**: eseguire Live, attendere testo, chiudere normalmente.

**Atteso**: sessione presente in cronologia dopo riavvio.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-501 — Autosave File — P0

**Atteso**: risultato File persistente dopo riavvio.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-502 — Nome sessione — P1

**Atteso**: nome personalizzato persistente e ricercabile.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-503 — Ricerca full-text — P1

**Atteso**: risultati corretti, nessun match spurio grave.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-504 — Export history TXT — P1

**Atteso**: file leggibile e coerente col transcript salvato.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-505 — Recovery audio — P0

Creare/interrompere una Live in una condizione in cui rimanga audio non trascritto.

**Atteso**

- recovery WAV visibile;
- può essere ritrascritto;
- può essere eliminato esplicitamente.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-506 — Retention transcript — P1

Testare con dati di prova/retention ridotta quando pratico.

**Atteso**: vengono eliminati soltanto elementi fuori policy.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-507 — Retention audio separata — P1

**Atteso**: retention registrazioni non cancella transcript e viceversa.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 18. Crash/recovery e resilienza

I test di terminazione forzata possono lasciare dati parziali intenzionalmente. Usare solo sessioni di prova.

## SYS-600 — Kill durante Live — P1

**Procedura**: terminare forzatamente il processo durante una sessione di prova.

**Atteso**: al riavvio, cronologia/recovery disponibili secondo lo stato scritto prima del crash.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-601 — Kill durante Riunione — P0

**Atteso**: journal recuperabile; avvio successivo non bloccato; nessun caricamento enorme in RAM.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-602 — whisper-server termina inaspettatamente — P0

**Atteso**: errore comprensibile; GUI resta viva; possibile recovery/riavvio del workflow secondo policy.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-603 — Microfono scollegato — P1

**Atteso**: errore/stato sorgente aggiornato, nessun freeze.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-604 — PipeWire/Pulse temporaneamente indisponibile — P2

**Atteso**: errore diagnostico, nessun crash incontrollato o loop ad alta CPU.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 19. Latenza e prestazioni Dictation

## SYS-700 — Raccolta 20 campioni — P0 per chiusura Phase 11

Eseguire almeno 20 sessioni brevi col modello che verrà usato normalmente.

```bash
.venv/bin/python tools/dictation_validation_report.py \
  ~/.local/share/ultratranscribr/dictation-metrics.jsonl
```

Registrare:

```text
Campioni:
activation → listening median:
activation → listening p95:
activation → first commit median:
activation → first commit p95:
activation → first insert median:
activation → first insert p95:
finalization median:
finalization p95:
max scheduler wait:
```

**Atteso**

- nessun campione di first insertion mancante senza una causa nota;
- valori coerenti e ripetibili;
- nessun peggioramento evidente dopo sessioni ripetute.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-701 — CPU/RAM/GPU a riposo — P1

**Atteso**: applicazione nel tray senza workflow attivo non consuma CPU/GPU in modo significativo o crescente.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-702 — Memoria dopo sessioni ripetute — P1

Eseguire almeno 20 Start/Stop Dictation e 10 Live brevi.

**Atteso**: nessuna crescita monotona evidente indicativa di leak.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-703 — Stress combinato — P2

Eseguire Live + File + brevi Dictation compatibili per almeno 10 minuti.

**Atteso**: scheduling coerente, GUI responsiva, nessun deadlock/processo orfano.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 20. Sicurezza e confini desktop

## SYS-800 — Navigazione WebEngine esterna — P0

**Atteso**: contenuti HTTP(S) esterni non vengono caricati nella WebEngine locale; eventuali link esterni usano il browser di sistema.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-801 — Un solo QWebChannel applicativo — P0

**Atteso**: overlay Dictation non crea un secondo backend QWebChannel e resta presentation-only.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-802 — Nessun fallback xdotool/pynput — P0

**Atteso**: se XDG Portal non è disponibile, Dictation fallisce chiaramente invece di utilizzare hook/input injection non previsti.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

## SYS-803 — Restore token non esposto alla UI — P0

**Atteso**: il token RemoteDesktop non compare nel bootstrap QWebChannel, nelle impostazioni frontend o nei log normali.

**Esito**: [ ] PASS [ ] FAIL [ ] SKIP

---

# 21. Checklist finale di accettazione

Una build può essere considerata **system validated** soltanto se:

- [ ] tutti i P0 applicabili sono PASS;
- [ ] suite pytest completa PASS;
- [ ] installer/self-check PASS;
- [ ] Dictation Doctor senza FAIL;
- [ ] GlobalShortcuts funzionante su KDE Wayland;
- [ ] RemoteDesktop keyboard-only funzionante;
- [ ] Dictation funziona in Firefox;
- [ ] Dictation funziona in Chromium/Chrome;
- [ ] Dictation funziona in LibreOffice Writer;
- [ ] Dictation funziona in Konsole;
- [ ] Dictation funziona in almeno un editor/IDE;
- [ ] Live Microfono PASS;
- [ ] Live Audio di sistema PASS;
- [ ] Live per-applicazione PASS;
- [ ] due Live simultanee PASS;
- [ ] File singolo e batch PASS;
- [ ] Riunione completa, diarizzazione e review PASS;
- [ ] history/recovery PASS;
- [ ] clipboard preservato durante Dictation;
- [ ] overlay non ruba focus;
- [ ] scheduling Dictation > Live > File osservato correttamente;
- [ ] nessun processo/sink posseduto resta orfano dopo Quit;
- [ ] almeno 20 campioni di latenza Dictation raccolti e salvati;
- [ ] nessun bug P0/P1 aperto senza una decisione esplicita.

---

# 22. Registro anomalie

| ID test | Gravità | Descrizione sintetica | Riproducibile | Log/screenshot | Stato |
| --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |

Gravità suggerita:

- **P0**: perdita dati, crash, deadlock, backend/processo corrotto, Dictation inutilizzabile, sicurezza/lifecycle rotto.
- **P1**: funzione principale errata ma con workaround.
- **P2**: edge case, compatibilità secondaria, problema cosmetico o prestazionale non bloccante.

---

# 23. Resoconto finale

```text
Commit testato:
Data:
Tester:

P0 PASS:
P0 FAIL:
P0 SKIP:

P1 PASS:
P1 FAIL:
P1 SKIP:

P2 PASS:
P2 FAIL:
P2 SKIP:

pytest:
Dictation Doctor:
Environment check:

Latenza Dictation median/p95:

Bug bloccanti:
Bug non bloccanti:

Verdetto:
[ ] APPROVATO
[ ] APPROVATO CON RISERVE
[ ] NON APPROVATO

Note finali:
```
