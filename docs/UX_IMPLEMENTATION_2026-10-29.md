# Ciclo UX del 29 ottobre 2026 — implementazione e verifiche

Questa è la verifica operativa di [ROADMAP_UX_2026-10-29.md](ROADMAP_UX_2026-10-29.md).
La scelta successiva dell'utente è sviluppare B1, B2 e B3; B4 e B5 rimangono
concept di confronto. Le tre modalità selezionabili condividono il documento.

## Collaudo successivo della copia installata

Il [rapporto del 30 ottobre](UX_INSTALLED_VERIFICATION_2026-10-30.md) completa
le verifiche delle voci implementate, documenta le correzioni emerse e il nuovo
layout File affiancato. Le misure e le limitazioni sotto restano la baseline
del primo ciclo; il rapporto successivo distingue le prove aggiuntive.

## Audit e baseline

Baseline Git: `9f43d67`; suite iniziale: **778 test passati in 29,43 s**.

| Area | Proprietario dello stato | Riscontro iniziale |
| --- | --- | --- |
| Audio Live | `BufferManager`, `LiveSessionManager`, `TranscriberThread` | La percentuale era numero di chunk / soglia di avviso, non capacità. Il denominatore non era temporale; il tempo dello scheduler misurava un'altra attesa. Gli aggiornamenti dipendevano dal consumer. |
| Testo e archivio | `TranscriptHistoryStore` | JSON atomici XDG; nomi manuali già persistenti, ma i fallback mostravano dispositivi e ID. |
| Revisione | `MeetingStore` + servizi Meeting | Originale e revisione già distinti; bozze con journal separato, ma conferma manuale richiesta. Nessuna pila Undo persistente. |
| Playback | `MeetingManager.audio_path` | Il player riceveva effettivamente il FLAC canonico a 16 kHz. Le catture Riunione venivano salvate dopo il resampling. |
| UI e threading | adapter Qt, `RecordModel`, QML | Worker con ritorni queued alla GUI, liste virtualizzate. Molti pannelli avevano altezze e metadati ridondanti. |
| Motori | Qwen3-ASR-1.7B, allineatori, Community-1; Whisper/SYCL | Pipeline Riunioni già distinta, con ownership esclusiva GPU e processi sequenziali. Preservata. |

## Modifiche consegnate

- **LIV-01:** append incrementale con conservazione della selezione; follow iniziale,
  sospensione con scroll/tastiera/scrollbar e comando “Torna al live”.
- **LIV-02/03:** misura dei campioni in FIFO convertita in secondi, conteggio dei chunk
  su disco e aggiornamenti dal producer anche durante inferenza. Percentuale storica
  e attesa scheduler restano grandezze distinte; dettagli nel log. Lo spill FIFO
  mantiene ordine e limita RAM. Stop/error salvano anche tutti i chunk ancora in coda,
  senza concatenare un'intera registrazione in memoria. Quando esiste già arretrato,
  i blocchi vengono raggruppati entro la finestra File, lasciando spazio all'overlap;
  senza arretrato il target Live rimane invariato. Nessun nuovo tempo di attesa
  per riempire il blocco più lungo e nessun cambio di modello. Nessun taglio del dato a 100%.
- **REV-01:** file importati copiati senza ricodifica, controllati con dimensione/SHA-256,
  conservati sotto gestione dell'app. Nuove catture Riunione a 48 kHz mono; mix a
  48 kHz per ascolto, derivato a 16 kHz separato per inferenza. I journal registrano
  la frequenza per il recupero. L'audio precedente privo di originale viene segnalato;
  il player non spaccia il derivato per originale. Eliminazione/retention includono
  originali gestiti e tracce, preservando il file esterno importato.
- **REV-02/03:** autosave con debounce 350 ms e journal 250 ms; flush all'uscita
  dall'editor e in chiusura. Conferma “salvate” soltanto dopo il ritorno del worker
  di persistenza. Errori conservano il draft e permettono retry. Cronologia di massimo
  500 comandi nel sidecar, testo originale immutabile e revisioni crescenti. Ctrl+Z,
  Ctrl+Shift+Z e Ctrl+Y usano la stessa pila anche dopo autosave/riavvio. Testo,
  assegnazioni e nomi speaker condividono Undo. Dopo un ricalcolo gli anchor impediscono
  Undo su interventi incompatibili, segnalando il conflitto. Le azioni speaker in coda
  non vengono scartate mentre è in corso un'altra scrittura.
- **UI/LIV/FIL:** intestazioni semplificate, componenti condivisi più compatti, menu
  lingua con nomi completi e valori backend; File in tre aree. Progresso corrente
  distinto dal conteggio degli elementi terminati: nessuna percentuale globale inventata.
  “Termina e completa” interrompe la cattura e drena il residuo; “Ferma” interrompe
  immediatamente e conserva il recovery. Dettagli non essenziali spostati nei tooltip.
- **MEET/REV-04/05:** archivio a due colonne su desktop e una al minimo, apertura
  con navigazione alla revisione; nove interlocutori raggiungibili con scrollbar.
  Dieci [concept confrontabili](ux/concepts/index.html); B1/B2/B3 implementati in QML
  come lista, indice/editor e documento. Posizione reale del player -> intervalli
  Python -> highlight simultaneo degli overlap. Seek dai timestamp, follow discreto,
  pausa durante editing/scroll e ripresa esplicita. Nessun WebEngine nel runtime.
- **HIST:** titoli automatici da sorgente/data reali, rinomina Live/File/Cronologia,
  recuperi con nome leggibile e ID/percorso tecnico invariato. Ricerca include il
  titolo visualizzato; record legacy restano leggibili senza riscrittura massiva.
- **SET/EXP:** configurazione ordinaria e download limitati a Whisper Large v3;
  selezioni persistite Turbo/Medium migrate a Large v3 senza eliminare i modelli
  scaricati. Enum storici leggibili dai componenti di compatibilità, ma API applicative
  e UI non offrono nuove operazioni con quei modelli. Qwen/Community-1 restano le
  Riunioni. VTT rimosso da renderer, allowlist, UI nativa e UI legacy; TXT/SRT verificati.
- **LOG:** funzionalità preservate; dettagli del buffer/scheduler registrati a livello debug.

## Verifiche automatiche

Comandi riproducibili:

```bash
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software .venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q main.py config core ui tests tools
.venv/bin/ruff check --select E9,F63,F7,F82 core ui config tools tests
bash -n install.sh
node --check ui/web/app.js
node --check ui/web/multi_live.js
node --check ui/web/settings_cleanup.js
node --check ui/web/file_history.js
node --check ui/web/meeting.js
pyside6-qmllint --unqualified info -I ui/qml ui/qml/*.qml
```

**Esito locale: 799 test passati in 40,69 s** (baseline 778).

Le verifiche nuove esercitano 50 interventi, ricaricamento e Undo/Redo persistenti,
fallimento storage senza falso successo, scrittura lenta con modifiche successive,
azioni speaker accodate, navigazione dopo autosave, testo e selezione Live,
tre editor con input Qt e focus conservato, intervalli sovrapposti e seek all'indietro,
originali alterati/mancanti, eliminazione che preserva il file esterno, recovery a
48 kHz e recupero completo FIFO/RAM/disco.

I test precedenti riferiti a input lingua testuali, conferma manuale e VTT sono stati
aggiornati ai nuovi comportamenti. I controlli TXT/SRT e i contratti legacy restano attivi.

## Collaudo reale Intel, senza simulazione GPU

`tools/validate_ux_runtime.py` usa cache dei modelli già presenti, dati XDG isolati
ed estratti pubblici locali; audio e testi non vengono pubblicati.

Prima prova completa, **batteria / alimentatore scollegato**:

| Misura | Osservato |
| --- | --- |
| Estratto inglese | 30,0 s |
| Pipeline effettiva | `qwen_meeting` |
| Elaborazione Qwen + allineatori + Community-1 | 178,76 s |
| Interventi prodotti | 3 |
| Picco PSS del processo e discendenti, campionamento 1 s | 5.254.182.912 byte |
| Originale importato identico byte per byte | Sì |
| Originale e derivato distinti | Sì |
| Modifica, Undo, Redo, TXT, SRT | Riusciti |
| Eliminazione audio gestito preservando il sorgente esterno | Riuscita |
| Ritorno effettivo a Whisper/SYCL | Riuscito |
| Prima richiesta Whisper dopo il cambio motore, 5 s di audio | 55,0 s |

### Ripetizione con alimentatore collegato

L'utente ha collegato l'alimentatore durante il collaudo. Le prove Whisper precedenti
sono state fermate e ripetute in una nuova sessione. Ogni richiesta è sorvegliata
ogni 200 ms, leggendo sia l'ingresso ACPI sia quello USB-C; una misura che perda
l'alimentazione non viene accettata come prova a corrente. Lo stato è rimasto
collegato per tutti i campioni delle cinque misure qui sotto.

| Prova a corrente | Osservato |
| --- | --- |
| Qwen/Community-1, stesso estratto 30 s e stesso SHA-256 | **100,24 s**, contro 178,76 s a batteria |
| Picco PSS Qwen/Community-1 a corrente | **5.243.057.152 byte** |
| Whisper, prima richiesta da 5 s della nuova sessione | **44,21 s** |
| Whisper, seconda/terza richiesta da 5 s | **7,31 / 7,62 s** |
| FIFO di 30 s, blocchi Live precedenti, backend già caldo | **38,73 s**, tre blocchi di testo |
| Stessa FIFO, recupero adattivo, stesso modello/backend | **33,56 s**, due blocchi di testo |
| Drain, entrambi i casi | Completato, zero audio residuo |
| Riduzione osservata del tempo di drain | **13,3%** |

La parte Qwen a corrente è rimasta collegata durante tutti i campioni dell'elaborazione;
la prima successiva misura Whisper è stata esclusa perché il sistema ha segnalato
una transizione temporanea dell'alimentazione. Le misure Whisper riportate provengono
dalla nuova sessione sorvegliata, non dalla prova interrotta.

Il costo della prima richiesta rimane significativo. Le richieste corte non hanno
lo stesso rapporto durata/tempo della Live. Anche il drain completo di questo estratto
rimane leggermente più lento del tempo reale: non viene dichiarato risolto ogni
problema prestazionale. Il recupero raggruppa solo audio già in coda, mantenendo il
modello Large v3 e il target ordinario quando non c'è arretrato. Non dimostra un
miglioramento WER né garantisce gli stessi tempi per altre registrazioni.

Riproduzione del confronto Live, con una cartella di output nuova:

```bash
.venv/bin/python tools/benchmark_live_runtime.py \
  --audio /percorso/estratto.wav \
  --model-cache ~/.cache/ultratranscribr/models/gguf \
  --output /percorso/nuovo-collaudo --require-ac
```

## Controllo visivo

Acquisizioni isolate riproducibili con `tools/capture_ui.py --populated --speakers 9`
a **1200×800**, **1650×930**, **1920×1080**, comprese le tre modalità di revisione.
[Confronto delle tre modalità implementate](ux/screenshots/index.html).
La modalità software verifica geometria e funzionalità, non certifica gli effetti
shader del renderer grafico. La fixture sostituisce soltanto il rilevamento GPU.

Misure preliminari a 1200×800 della configurazione (stessa sorgente sistema):

| Pannello | Prima, px | Dopo, px | Riduzione |
| --- | --- | --- | --- |
| Live | 445,59 | 224 | 49,7% |
| File | 394 | 290 | 26,4% |
| Riunione | 632 | circa 421, con altezza derivata dai contenuti | circa 33% |
| Modello Whisper | 358,80 | 190 | 47,0% |

Il cambio di larghezza Live/File è intenzionale: l'area di stato ridondante è stata
rimossa. Non sono confronti pixel-per-pixel di superfici aventi la stessa larghezza.

## Limiti e attività non dichiarate complete

- **SET-02/03:** Avanzate rimane. Il collaudo breve non dimostra parametri ottimali
  su dataset italiano/inglese rappresentativi; non è stato svolto un nuovo sweep
  WER/CER/errore speaker sufficiente a giustificare la rimozione della scheda.
- **TEST-01:** Dictation Doctor interroga con successo KDE/Wayland, session bus,
  GlobalShortcuts e RemoteDesktop. Questo non certifica Push-to-Talk, focus/paste
  nelle applicazioni esterne, permessi interattivi e ripristino clipboard end-to-end.
- Il confronto con alimentatore viene riportato separatamente dalle prime misure a
  batteria; non viene attribuita all'alimentazione una causa esclusiva.
- Il test GPU di 30 s e le prove logiche non sostituiscono una registrazione reale
  multi-sorgente di ore, nove voci reali, test uditivi e validazione dell'hardware a
  48 kHz. Richieste non supportate dal dispositivo falliscono esplicitamente.
- Il confronto temporale del player è verificato su WAV/FLAC. Contenitori video
  con tracce audio multiple o timestamp di partenza non zero richiedono ulteriori
  prove dedicate prima di certificare la corrispondenza in tutti i casi.
- Le vecchie registrazioni già ridotte a 16 kHz non possono riacquistare frequenze
  perdute. La disponibilità dell'originale è indicata per ogni documento.
- La digitazione dentro il debounce non ancora confermata può andare persa in una
  terminazione forzata precedente al checkpoint; il journal riduce questa finestra.
  “Salvate” indica conferma persistente, non semplice aggiornamento della card.

## Review architetturale

Nessun nuovo database e nessuna migrazione a HTML. JSON, originali e comandi Undo
sono di proprietà del core; adapter e task group coordinano I/O fuori dalla GUI;
QML possiede soltanto presentazione/focus/layout/follow. Il lookup temporale è
incrementale, mentre un seek all'indietro ricostruisce lo stato dagli eventi.
La verifica SHA dell'originale avviene in background all'apertura, non per frame.
Le liste restano virtualizzate; le alternative di editor non duplicano il documento.
