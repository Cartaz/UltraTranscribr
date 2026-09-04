# UltraTranscribr

UltraTranscribr è un'applicazione desktop Linux local-first per trascrizione **Live**, **File**, **Riunione** e **Dettatura globale**. L'interfaccia usa PySide6/Qt WebEngine e QWebChannel; l'inferenza resta locale.

La configurazione di riferimento è CachyOS/Arch Linux con GPU Intel e due runtime di accelerazione:

- `whisper.cpp` compilato con **GGML SYCL / Level Zero** per Whisper;
- **PyTorch XPU** per diarizzazione pyannote e separazione vocale Demucs.

## Funzioni principali

- Live da microfono, audio di sistema o singolo stream/applicazione.
- Dettatura globale su KDE/Wayland tramite XDG Desktop Portal.
- Trascrizione File singola o batch con timestamp ed export `.txt`, `.srt`, `.vtt`.
- Modalità Musica con isolamento vocale Demucs/HTDemucs su Intel XPU.
- Riunioni realtime multi-sorgente oppure da registrazione audio/video esistente.
- Batch Riunioni sequenziale per elaborare più registrazioni senza inferenze GPU concorrenti, con lingua e numero interlocutori configurabili per ogni file.
- Fino a 8 sorgenti realtime conservate come tracce FLAC separate e sincronizzate.
- Diarizzazione locale ad alta accuratezza con `pyannote/speaker-diarization-community-1`.
- Timestamp Whisper parola-per-parola per separare cambi di interlocutore anche dentro un singolo segmento di trascrizione.
- `exclusive_speaker_diarization` per assegnare il testo e diarizzazione regolare per segnalare il parlato realmente sovrapposto.
- Numero di interlocutori noto opzionale e ricalcolo della sola diarizzazione su riunioni già trascritte.
- Correzione manuale dello speaker per ogni intervento, inclusi i casi `Speaker ?`, senza sovrascrivere il risultato automatico.
- Nomi speaker e correzioni manuali senza creare una libreria biometrica/voiceprint.
- Cronologia persistente, recovery audio e retention configurabile.
- UI Dark Neumorphism con stato canonico mantenuto in Python.

## Requisiti

Configurazione supportata di riferimento:

- Linux x86_64, prima classe CachyOS/Arch + KDE;
- Python 3.12+;
- Intel oneAPI in `/opt/intel/oneapi`;
- Intel Compute Runtime e Level Zero;
- GPU Intel visibile a SYCL e PyTorch XPU;
- `git`, `cmake`, `ffmpeg`;
- PipeWire-Pulse/PulseAudio con `pactl` per cattura di sistema/per-applicazione;
- per Dettatura globale su Wayland: `xdg-desktop-portal` e `xdg-desktop-portal-kde`.

Pacchetti Arch/CachyOS tipici:

```bash
sudo pacman -S --needed \
  python git cmake ffmpeg \
  intel-oneapi-basekit intel-compute-runtime level-zero \
  libpulse pipewire-pulse xdg-desktop-portal xdg-desktop-portal-kde
```

## Installazione

```bash
chmod +x install.sh
./install.sh
```

Avvio canonico:

```bash
.venv/bin/python main.py
```

`install.sh` è non interattivo rispetto ai componenti di inferenza e installa sempre:

1. dipendenze applicative Python;
2. PyTorch e torchaudio Intel XPU pinning stabile;
3. TorchCodec compatibile richiesto da pyannote;
4. `pyannote.audio` e `demucs-infer`;
5. `whisper.cpp` compilato con SYCL;
6. modello Whisper predefinito `large-v3` e modello VAD;
7. integrazione desktop;
8. self-check finale dell'ambiente.

Demucs non è più un componente opzionale dell'installazione. L'opzione **Isola voce** resta una scelta dell'utente durante la trascrizione musicale, ma quando viene richiesta deve funzionare sul runtime XPU: UltraTranscribr non continua silenziosamente sul file originale e non ripiega sulla CPU.

Per forzare la ricompilazione di whisper.cpp:

```bash
ULTRATRANSCRIBR_FORCE_REBUILD=1 ./install.sh
```

## Modelli Whisper

La UI gestisce:

- Large v3 — `large-v3` (**predefinito**)
- Large v3 Turbo — `large-v3-turbo`
- Medium — `medium`

I modelli sono mantenuti nella cache XDG di UltraTranscribr e possono essere gestiti dalla UI.

## Riunioni e diarizzazione

Realtime e file convergono nella stessa pipeline:

```text
microfono / sistema / applicazioni        file audio/video
              |                                  |
      tracce FLAC separate                normalizzazione
              |                                  |
              +---------- FLAC mono 16 kHz ------+
                                 |
                                 v
                    Whisper large-v3 / SYCL
                 segmenti + timestamp parole
                                 |
                                 v
                 pyannote Community-1 / XPU
          segmentation + speaker embeddings + VBx
                       /                 \
                      v                   v
       exclusive diarization       regular diarization
         assegna le parole        rileva overlap reale
                      \                   /
                       v                 v
                    allineamento word-level
                                 |
                                 v
                         review / export
```

Se il numero di interlocutori è noto viene passato direttamente a Community-1; `0` mantiene il conteggio automatico. UltraTranscribr assegna identificatori tecnici `SPEAKER_00`, `SPEAKER_01`, ecc. e non tenta di riconoscere l'identità reale delle persone. I nomi vengono aggiunti manualmente nella review e non viene mantenuta alcuna libreria di campioni vocali.

### Batch di registrazioni

In **Riunione → Da registrazione** è possibile selezionare più file audio/video e avviarli come coda FIFO. La coda esegue una sola pipeline Meeting alla volta, quindi Whisper/SYCL e Community-1/XPU non competono tra loro per GPU e RAM.

I campi generali di lingua e numero interlocutori diventano valori predefiniti per i file appena selezionati. Prima di avviare il batch ogni registrazione ha una propria riga modificabile: lingua e numero di interlocutori (`0` = automatico, massimo `20`) vengono congelati nel relativo job. È quindi possibile mescolare nello stesso batch, per esempio, riunioni con 4, 5 e 9 interlocutori.

Se un job fallisce, viene marcato in errore e la coda continua con quello successivo. Le riunioni completate vengono archiviate senza aprire automaticamente ogni review. **Annulla coda** interrompe la riunione corrente e annulla quelle ancora in attesa; **Pulisci completate** pulisce soltanto la vista della coda e non cancella l'Archivio. La coda è transitoria e non viene ripristinata dopo un riavvio dell'applicazione. La descrizione dettagliata è in `docs/MEETING_BATCH.md`.

### Allineamento speaker e review

Per le nuove trascrizioni UltraTranscribr conserva i timestamp parola-per-parola restituiti da whisper.cpp. Ogni parola viene riconciliata con la timeline `exclusive_speaker_diarization`: se un singolo segmento Whisper contiene prima una domanda di uno speaker e subito dopo la risposta di un altro, la review viene spezzata automaticamente al cambio interlocutore invece di assegnare l'intero blocco a una sola persona.

La timeline Community-1 regolare viene conservata separatamente e viene usata soltanto per rilevare sovrapposizioni acustiche reali, cioè intervalli in cui due speaker parlano contemporaneamente. In questi casi la review mostra un avviso e richiede controllo umano: da una singola traccia mono non è sempre possibile attribuire in modo affidabile ogni parola quando due persone parlano nello stesso istante.

Ogni intervento della review dispone inoltre di una scelta speaker manuale. L'override è persistito separatamente da `speaker_id`, quindi non cancella l'assegnazione automatica ed è possibile tornare a **Automatico**. Lo stesso meccanismo permette di risolvere manualmente i segmenti `Speaker ?`. Export TXT/SRT/VTT usa l'override quando presente.

Le riunioni create prima dell'introduzione dei timestamp parola-per-parola continuano a funzionare con l'allineamento segment-level storico. Un semplice ricalcolo della diarizzazione non può inventare word timestamps che non erano stati salvati, ma la correzione manuale dello speaker resta disponibile.

### Ricalcolo della diarizzazione

Dalla review di una Riunione è possibile scegliere nuovamente il numero di interlocutori e usare **Ricalcola diarizzazione**. Questo percorso non avvia whisper.cpp: riusa il FLAC canonico conservato e i segmenti Whisper timestampati già persistiti, quindi sostituisce soltanto la diarizzazione e il relativo allineamento speaker.

Il risultato precedente viene sostituito solo dopo un ricalcolo completato con successo. Se Community-1 fallisce o l'operazione viene annullata, review e diarizzazione già salvate restano utilizzabili. Le correzioni manuali di testo e speaker vengono riapplicate quando la loro identità di provenienza Whisper è ancora compatibile; gli ID speaker vengono inoltre stabilizzati per sovrapposizione temporale con la diarizzazione precedente, così i nomi manuali restano associati per quanto possibile allo stesso interlocutore.

Il ricalcolo richiede che l'audio della Riunione sia ancora conservato. Dopo **Elimina audio** o dopo la retention automatica, la sola trascrizione testuale non è sufficiente per eseguire nuovamente Community-1.

### Primo download di Community-1

Community-1 è utilizzabile localmente ma il repository ufficiale Hugging Face richiede una tantum l'accettazione delle condizioni. Prima della prima Riunione:

1. accettare le condizioni di `pyannote/speaker-diarization-community-1` su Hugging Face;
2. autenticare la macchina:

```bash
.venv/bin/hf auth login
```

Al primo uso UltraTranscribr risolve la revisione del modello, scarica lo snapshot in una directory temporanea e lo rende attivo solo dopo aver verificato che il payload sia completo. La revisione scaricata viene registrata nella cache locale; le esecuzioni successive caricano il modello da disco.

Il token Hugging Face non viene scritto nelle impostazioni di UltraTranscribr.

## Runtime GPU e policy di fallback

UltraTranscribr usa un unico proprietario del runtime PyTorch XPU per Community-1 e Demucs. Il preflight verifica `torch.xpu`, rileva almeno una GPU e svolge una reale operazione tensoriale prima di considerare il runtime disponibile.

Non esistono fallback automatici a:

- diarizzazione Sherpa/ONNX;
- diarizzazione CPU;
- Demucs CPU;
- trascrizione del mix originale quando l'utente ha richiesto l'isolamento vocale.

Un requisito GPU non soddisfatto produce invece un errore esplicito e diagnosticabile.

## Self-check

```bash
source /opt/intel/oneapi/setvars.sh
.venv/bin/python -m core.environment_check
```

Il report controlla almeno Python, oneAPI, Level Zero, Intel Compute Runtime/GPU, PyTorch XPU, ffmpeg, whisper-server SYCL, modelli Whisper/VAD e le dipendenze pyannote/Demucs.

Per la Dettatura globale:

```bash
.venv/bin/python tools/dictation_doctor.py
```

## Dati e privacy

Percorsi XDG principali:

```text
Configurazione:      ~/.config/ultratranscribr/
Dati/storico:        ~/.local/share/ultratranscribr/
Registrazioni:       ~/.local/share/ultratranscribr/recordings/
Cache/modelli:       ~/.cache/ultratranscribr/
```

Trascrizione, diarizzazione e separazione vocale vengono eseguite localmente. La rete è necessaria per il download iniziale dei modelli; l'audio e i transcript non vengono inviati a Hugging Face dalla pipeline di diarizzazione.

## Sviluppo e test

```bash
.venv/bin/python -m compileall -q main.py config core ui tests tools
.venv/bin/python -m pytest -q
bash -n install.sh
node --check ui/web/app.js
node --check ui/web/multi_live.js
node --check ui/web/settings_cleanup.js
node --check ui/web/file_history.js
node --check ui/web/meeting.js
```

La CI headless verifica logica, contratti, sintassi e lifecycle senza fingere la presenza di una GPU Intel reale. Il test fisico di PyTorch XPU, Community-1 e HTDemucs resta parte del self-check/installazione sul sistema target.

La documentazione della pipeline Riunione è in `docs/MEETING_PIPELINE.md`; il batch Riunioni è descritto in `docs/MEETING_BATCH.md`; quella della Dettatura globale in `docs/DICTATION.md` e `docs/DICTATION_VALIDATION.md`.

## Licenza

MIT.
