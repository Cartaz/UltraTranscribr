# UltraTranscribr

UltraTranscribr è un'applicazione desktop Linux per trascrizione **Live**, **File** e **Riunione** basata su `whisper.cpp`, con accelerazione **Intel SYCL / Level Zero** e interfaccia PySide6 + WebEngine.

Il progetto è pensato principalmente per **CachyOS / Arch Linux** con GPU Intel compatibile con Compute Runtime/Level Zero.

## Funzioni principali

- Trascrizione Live da audio di sistema, microfono o singolo stream/applicazione.
- Più sessioni Live indipendenti con inferenza serializzata su un singolo `whisper-server`.
- Registrazione opzionale delle sole Live da microfono, per singola sessione e con default OFF.
- Modalità **Riunione** con registrazione microfono obbligatoria, trascrizione finale timestampata, diarizzazione locale e revisione manuale.
- Assegnazione manuale dei nomi agli speaker senza riconoscimento biometrico dell'identità.
- Correzione manuale del transcript di Riunione mantenendo separato il testo Whisper raw originale.
- Player della registrazione con seek dai singoli interventi e export speaker-aware `.txt`, `.srt`, `.vtt`.
- Trascrizione batch di più file audio/video con coda FIFO, avanzamento reale e cancellazione.
- Selezione multipla e drag-and-drop di file locali.
- Modalità Musica opzionale con Demucs per isolamento vocale.
- Modelli UI supportati: `large-v3`, `large-v3-turbo`, `medium`.
- Cronologia persistente delle trascrizioni e recovery audio per segmenti Live non trascritti.
- Timestamp persistenti per le trascrizioni File ed export `.txt`, `.srt` e `.vtt` quando disponibili.
- Ricerca full-text nella cronologia.
- Profili di post-processing opzionali salvati separatamente dal transcript originale.
- Routing PipeWire/PulseAudio reversibile per la cattura per-applicazione.
- UI Dark Neumorphism con backend Python locale via QWebChannel.

## Ambiente supportato

Configurazione di riferimento:

- CachyOS o Arch Linux x86_64.
- Python 3.11 o superiore.
- Intel oneAPI Base Toolkit installato in `/opt/intel/oneapi`.
- Intel Compute Runtime e Level Zero.
- GPU Intel visibile al runtime Level Zero/SYCL.
- `git`, `cmake`, `ffmpeg`.
- PipeWire-Pulse o PulseAudio con `pactl` per audio di sistema e routing per-applicazione.

Pacchetti Arch/CachyOS tipici:

```bash
sudo pacman -S --needed \
  python git cmake ffmpeg \
  intel-oneapi-basekit intel-compute-runtime level-zero \
  libpulse pipewire-pulse
```

I nomi dei pacchetti possono cambiare nei repository Arch/CachyOS. L'installer verifica comunque i componenti effettivamente disponibili prima di procedere.

## Installazione

Dalla directory della repository:

```bash
chmod +x install.sh
./install.sh
```

Avvio:

```bash
.venv/bin/python main.py
```

L'installer:

1. individua Python 3.11+;
2. crea `.venv` se necessario;
3. installa le dipendenze Python da `requirements.txt`, inclusa `sherpa-onnx` per la diarizzazione locale;
4. carica Intel oneAPI;
5. clona e compila il commit pin di `whisper.cpp` con SYCL;
6. installa `whisper-server` e le librerie necessarie nella `.venv`;
7. scarica il modello predefinito `large-v3-turbo` e il modello VAD se mancanti;
8. crea il launcher desktop locale;
9. esegue un self-check completo dell'ambiente.

I modelli ONNX di diarizzazione vengono invece scaricati **solo al primo processamento di una Riunione**. Non sono necessari per Live o File e non richiedono servizi cloud durante l'uso.

### Reinstallazioni veloci / idempotenza

`install.sh` conserva fingerprint per le dipendenze Python e per la build di `whisper.cpp`.

Se non sono cambiati Python, `requirements.txt`, commit whisper.cpp, compilatori o configurazione CMake, una nuova esecuzione salta automaticamente i passaggi costosi già validi.

Per forzare la ricompilazione SYCL:

```bash
ULTRATRANSCRIBR_FORCE_REBUILD=1 ./install.sh
```

### Demucs opzionale

Durante un'installazione interattiva viene chiesto se installare Demucs + PyTorch CPU per la modalità Musica.

Per abilitarlo senza prompt:

```bash
ULTRATRANSCRIBR_INSTALL_DEMUCS=1 ./install.sh
```

Per saltarlo esplicitamente:

```bash
ULTRATRANSCRIBR_INSTALL_DEMUCS=0 ./install.sh
```

Demucs non è richiesto per la trascrizione normale o per Riunione.

## Self-check dell'ambiente

Dopo l'installazione il controllo viene eseguito automaticamente. Può essere rilanciato manualmente con:

```bash
source /opt/intel/oneapi/setvars.sh
.venv/bin/python -m core.environment_check
```

Il report verifica:

- Python 3.11+;
- Intel oneAPI;
- Level Zero loader;
- Intel Compute Runtime;
- GPU Intel;
- `ffmpeg`;
- `whisper-server` compilato con SYCL;
- modello ASR predefinito;
- modello VAD;
- dipendenze Python richieste;
- Demucs/PyTorch come componente opzionale.

Un requisito obbligatorio mancante produce exit code diverso da zero.

## Modelli

La UI espone soltanto:

- Large v3 — `large-v3`
- Large v3 Turbo — `large-v3-turbo`
- Medium — `medium`

`large-v3-turbo` è il modello predefinito e viene predisposto da `install.sh`. Gli altri modelli possono essere scaricati o eliminati dalla sezione di gestione modelli dell'applicazione.

I modelli Whisper sono salvati in:

```text
~/.cache/ultratranscribr/models/gguf/
```

I download interrotti usano file `.part` riprendibili e, una volta completati, vengono verificati tramite SHA-256 salvato accanto al modello.

I modelli per la diarizzazione sherpa-onnx vengono mantenuti separatamente nella cache di UltraTranscribr e sono usati soltanto dal workflow Riunione.

## Uso

### Live

La sezione Live permette di creare sessioni indipendenti scegliendo una sorgente:

- **Audio di sistema**: monitor dell'uscita predefinita.
- **Microfono**: input audio reale.
- **Applicazione/stream**: singolo playback stream PipeWire/PulseAudio isolato temporaneamente in un null sink dedicato.

Per ogni sessione sono disponibili Stop e Drain. Drain interrompe la cattura ma lascia terminare la trascrizione dell'audio già presente nel buffer.

#### Registrazione opzionale Live Microfono

Quando la sorgente selezionata è **Microfono**, compare il toggle **Salva registrazione**.

- default: **OFF**;
- viene deciso prima dello Start della singola sessione;
- Audio di sistema e Applicazione non sono interessati;
- quando attivo, lo stesso PCM mono 16 kHz inviato alla pipeline Whisper viene anche scritto dal recorder persistente;
- la registrazione finale è FLAC lossless;
- dalla Cronologia l'audio può essere ascoltato o eliminato senza cancellare la trascrizione.

Una Live Microfono registrata resta una normale sessione Live: non viene automaticamente diarizzata o trasformata in Riunione.

### Riunione

La tab **Riunione** è pensata per riunioni, interviste e conversazioni con più interlocutori.

Durante la registrazione:

1. viene usato esclusivamente il microfono selezionato;
2. la registrazione è sempre attiva;
3. l'audio viene journalizzato progressivamente in PCM16 mono 16 kHz;
4. il journal viene sincronizzato periodicamente su disco per ridurre la perdita possibile in caso di crash;
5. a chiusura normale viene finalizzato in FLAC lossless senza caricare l'intera registrazione in RAM.

Una Riunione è mutuamente esclusiva con Live e File. Durante il workflow non vengono avviate altre trascrizioni, recovery o operazioni distruttive sui modelli/impostazioni.

Dopo **Termina riunione**:

```text
registrazione completa
        ↓
trascrizione Whisper finale con timestamp
        ↓
diarizzazione locale sherpa-onnx
        ↓
allineamento speaker ↔ segmenti Whisper
        ↓
review manuale
```

La diarizzazione assegna identificatori tecnici stabili come `SPEAKER_00`, `SPEAKER_01`, ecc. UltraTranscribr **non tenta di riconoscere automaticamente l'identità delle persone**.

Se il numero di interlocutori è noto può essere indicato prima dell'elaborazione; altrimenti viene usato il clustering automatico.

Quando due speaker hanno una sovrapposizione temporale troppo simile sullo stesso segmento, il risultato viene marcato come incerto invece di inventare un'assegnazione certa.

#### Revisione manuale

Nella review della Riunione è possibile:

- rinominare `Speaker 1`, `Speaker 2`, ecc. con nomi scelti manualmente;
- cambiare i nomi in qualunque momento e propagare la label a tutti gli interventi;
- correggere manualmente il testo di ogni intervento;
- cliccare un intervento per portare il player al timestamp corrispondente;
- ascoltare la registrazione completa;
- eliminare soltanto l'audio conservando transcript e review;
- esportare la versione revisionata in `.txt`, `.srt` o `.vtt`.

Il testo Whisper raw, i segmenti timestampati originali e i risultati della diarizzazione restano separati dai nomi e dalle correzioni manuali. La review non sovrascrive mai la fonte originale.

### Recovery registrazioni microfono

Durante una registrazione persistente il file di lavoro è un journal append-only `.pcm.part`. Dopo un arresto anomalo, UltraTranscribr rileva i journal rimasti e li converte in FLAC in background, senza bloccare l'apertura della GUI. Per le Riunioni associate viene aggiornato lo stato a `interrupted`; l'audio recuperato resta disponibile per revisione o elaborazioni successive.

### File e batch

La sezione File può accettare uno o più file locali. Ogni elemento viene normalizzato in PCM16 mono 16 kHz e trascritto progressivamente.

Con più file:

- i file vengono inseriti in una coda FIFO;
- viene eseguito un solo worker File alla volta;
- ogni file mantiene una propria sessione nella cronologia;
- **Ferma** interrompe il file corrente e lascia proseguire la coda con il successivo;
- **Annulla coda** interrompe il corrente e marca come annullati anche i file ancora pendenti;
- i job completati possono essere rimossi dalla visualizzazione senza cancellare la relativa cronologia.

È possibile aggiungere file con **Sfoglia multipli** oppure trascinando file locali nella finestra di UltraTranscribr.

### Timestamp ed export

Per le nuove trascrizioni File, UltraTranscribr conserva i segmenti temporizzati restituiti da whisper.cpp insieme al transcript raw.

Dalla Cronologia sono disponibili:

- `.txt` per il testo;
- `.srt` quando esistono segmenti temporizzati;
- `.vtt` quando esistono segmenti temporizzati.

Le Riunioni esportano invece la **versione revisionata speaker-aware**, usando il nome manuale quando presente e `Speaker N` come fallback.

Le vecchie sessioni salvate prima dell'introduzione dei timestamp restano leggibili; semplicemente non espongono gli export sottotitoli se non possiedono segmenti temporizzati.

### Cronologia, ricerca e recovery

Le trascrizioni vengono persistite progressivamente. La Cronologia supporta ricerca case-insensitive con semantica AND su transcript e metadati utili, inclusa la sorgente/file.

Se un segmento Live non può essere trascritto dopo i retry previsti, l'audio viene conservato come WAV di recovery e può essere ritrascritto dalla UI.

### Post-processing

La Cronologia può generare viste derivate del transcript, ad esempio una normalizzazione leggera o una suddivisione in paragrafi.

Il transcript raw rimane sempre la fonte di verità: i risultati del post-processing vengono salvati separatamente in `derived_outputs` e non sovrascrivono mai il testo originale.

## Impostazioni

Le impostazioni sono divise in:

- **Normali**: modello, lingua, sorgente e VAD.
- **Avanzate**: beam size, chunking, override sink, porta server e parametri tecnici SYCL/backend.

La retention audio delle Riunioni è separata dalla retention della cronologia. `0` disabilita la cancellazione automatica dell'audio.

La geometria della finestra viene salvata automaticamente. La dimensione minima resta 1200×800.

## Percorsi dati

UltraTranscribr segue le directory XDG:

```text
Configurazione:      ~/.config/ultratranscribr/
Log app:             ~/.config/ultratranscribr/ultratranscribr.log
Dati/storico:        ~/.local/share/ultratranscribr/
Registrazioni:       ~/.local/share/ultratranscribr/recordings/
Metadata riunioni:   ~/.local/share/ultratranscribr/meetings/
Cache/modelli:       ~/.cache/ultratranscribr/
```

I log applicativi ruotano automaticamente a circa **5 MiB** mantenendo fino a **4 backup**:

```text
ultratranscribr.log
ultratranscribr.log.1
...
ultratranscribr.log.4
```

Il log del processo `whisper-server` usato durante il runtime è invece nella directory del progetto:

```text
.venv/whisper-server.log
```

## Troubleshooting

### `GPU SYCL non disponibile`

Eseguire:

```bash
source /opt/intel/oneapi/setvars.sh
.venv/bin/python -m core.environment_check
```

Controllare in particolare le righe Level Zero, Compute Runtime e Intel GPU.

### `whisper-server non trovato` o non SYCL

Forzare una nuova build:

```bash
ULTRATRANSCRIBR_FORCE_REBUILD=1 ./install.sh
```

Controllare inoltre:

```text
.venv/whisper-server.log
```

### Audio di sistema non rilevato

Verificare PipeWire/PulseAudio:

```bash
pactl info
pactl get-default-sink
pactl list short sources
```

Nella UI usare **Aggiorna** nella sezione Live e consultare i diagnostici audio.

### Stream applicazione scomparso

Gli stream per-applicazione esistono soltanto mentre l'app sta riproducendo audio. Avviare la riproduzione, aggiornare l'elenco e selezionare lo stream corretto.

UltraTranscribr ripristina il routing originale quando la sessione termina e tenta anche la pulizia di eventuali null sink rimasti dopo un crash.

### Modello mancante o download interrotto

Aprire la gestione modelli nella UI e riprendere il download. I `.part` vengono riutilizzati automaticamente.

### La prima Riunione resta su download diarizzazione

Il primo processamento Riunione scarica i modelli ONNX di segmentation e speaker embedding. Il download non coinvolge audio o transcript dell'utente; serve soltanto a predisporre la pipeline locale. Dopo il download i modelli vengono riutilizzati dalla cache.

### Riunione con speaker incerto

`Speaker ?` indica che il segmento non aveva una sovrapposizione sufficientemente chiara con un singolo interlocutore. È intenzionale: UltraTranscribr evita di assegnare un'identità quando due speaker risultano troppo vicini temporalmente. Il testo resta comunque correggibile manualmente.

### Demucs non disponibile

La trascrizione normale continua a funzionare. Per installarlo successivamente:

```bash
ULTRATRANSCRIBR_INSTALL_DEMUCS=1 ./install.sh
```

## Sviluppo e test

L'ambiente di sviluppo usa la stessa `.venv` dell'applicazione.

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
bash -n install.sh
node --check ui/web/app.js
node --check ui/web/multi_live.js
node --check ui/web/settings_cleanup.js
node --check ui/web/power_user.js
node --check ui/web/phase10.js
node --check ui/web/phase10_hardening.js
```

La CI GitHub esegue questi controlli ad ogni pull request. I test Phase 10 usano recorder, capture, Whisper e diarizzazione finti/deterministici: la CI non scarica modelli ONNX e non richiede hardware audio reale.

## Packaging Arch

La repository contiene anche un `PKGBUILD` per packaging Arch. Il percorso di installazione locale supportato e documentato per lo sviluppo resta tuttavia:

```bash
chmod +x install.sh
./install.sh
.venv/bin/python main.py
```

## Licenza

MIT.
