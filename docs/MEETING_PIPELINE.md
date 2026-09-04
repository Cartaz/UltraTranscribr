# Meeting pipeline

La modalità Riunione non implementa una pipeline microfono separata. Aggiunge diarizzazione, labeling e revisione a due ingressi canonici:

- realtime multi-sorgente: microfono, audio di sistema o singola applicazione, fino a 8 sorgenti;
- file audio/video già registrato.

## Realtime

Ogni sorgente viene risolta dal servizio condiviso con Live. Le sorgenti applicazione usano lease di routing PipeWire/PulseAudio reversibili possedute dall'application layer. Ogni sorgente viene registrata separatamente in FLAC mono 16 kHz. Alla chiusura le tracce vengono allineate usando il timestamp monotonic del primo campione e mixate a blocchi in un FLAC canonico, senza caricare l'intera riunione in RAM.

## File

Il media importato viene normalizzato in FLAC mono 16 kHz. La registrazione canonica risultante entra direttamente nella stessa fase di analisi del realtime.

## Analisi comune

```text
realtime sources -> separate tracks -> synchronized canonical mix --+
                                                                  |
file media ---------> normalized canonical recording -------------+
                                                                  |
                                                                  v
                                                     final Whisper transcript
                                                     whisper.cpp / SYCL
                                                segments + word timestamps
                                                                  |
                                                                  v
                                              pyannote Community-1 / XPU
                                           segmentation + embeddings + VBx
                                                        /                 \
                                                       v                   v
                                      exclusive speaker diarization   speaker diarization
                                           text assignment            overlap evidence
                                                        \                 /
                                                         v               v
                                                   meeting_alignment
                                                         word-level
                                                             |
                                                             v
                                                      review / export
```

La diarizzazione usa esclusivamente `pyannote/speaker-diarization-community-1`. Se il numero di interlocutori è noto viene passato come `num_speakers`; `0` mantiene il conteggio automatico.

Le reti neurali di Community-1 vengono eseguite sul runtime condiviso PyTorch XPU della GPU Intel. UltraTranscribr non effettua fallback automatico a CPU o al precedente backend sherpa-onnx: un runtime XPU non disponibile produce un errore esplicito.

Il modello Community-1 viene scaricato una sola volta nella cache XDG dell'applicazione e poi caricato da disco. Il repository ufficiale Hugging Face è gated: prima del primo download l'utente deve accettarne le condizioni e autenticare localmente `huggingface-hub`; il token non viene salvato nelle impostazioni di UltraTranscribr.

## Word-level speaker alignment

Whisper viene interrogato in `verbose_json` con token timestamps. `FileTranscriberThread` conserva i record `words` insieme ai segmenti canonici nello storico Python:

```text
segment
  start / end / text
  words[]
    word / start / end / probability
```

`meeting_alignment.align_speakers` usa `exclusive_speaker_diarization` per assegnare ogni parola a uno speaker. Parole contigue attribuite allo stesso speaker vengono raggruppate in un intervento di review. Se un singolo segmento Whisper contiene un cambio A -> B, il segmento viene quindi spezzato senza modificare il transcript raw.

Le riunioni storiche che non contengono `words` restano compatibili: per esse l'allineamento usa il precedente calcolo a livello di segmento basato sulla sovrapposizione temporale dominante. Non viene inventato timing che non esiste.

## Parlato sovrapposto

Community-1 restituisce due timeline con responsabilità diverse:

- `exclusive_speaker_diarization`: un solo speaker per istante; è la sorgente canonica per attribuire il testo;
- `speaker_diarization`: può contenere più speaker simultanei; viene conservata separatamente per segnalare vero overlap acustico.

Il semplice passaggio sequenziale da A a B non è etichettato come overlap. La review segnala sovrapposizione soltanto quando due turni della timeline regolare condividono realmente un intervallo temporale significativo.

Con audio mono e due persone che pronunciano parole nello stesso istante, l'attribuzione testuale può restare intrinsecamente ambigua. UltraTranscribr non finge quindi una separazione certa: mostra l'overlap e lascia la decisione finale all'utente.

## Correzione manuale dello speaker

Ogni intervento di review conserva separatamente:

- `speaker_id`: risultato automatico;
- `speaker_override`: scelta manuale opzionale.

La UI permette di scegliere uno degli speaker noti o tornare a **Automatico**. Questo rende correggibili anche i segmenti `Speaker ?` senza distruggere il dato prodotto dal modello. `MeetingStore` valida l'override contro gli speaker effettivamente presenti e TXT/SRT/VTT usano lo speaker effettivo (`override` se presente, altrimenti automatico).

Le correzioni di testo continuano a vivere nel campo `text`, separato da `raw_text`. Le due classi di correzione sono quindi indipendenti e reversibili rispetto all'output automatico.

## Ricalcolo su una Riunione già trascritta

La review espone **Ricalcola diarizzazione** finché il FLAC canonico della Riunione esiste. Il ricalcolo è una pipeline distinta solo nel lifecycle, non nell'algoritmo di diarizzazione:

```text
FLAC canonico persistito -----------+
                                    |
segmenti Whisper persistiti --------+--> Community-1 / XPU
                                             |
                                  +----------+----------+
                                  |                     |
                         exclusive timeline       regular timeline
                                  |                     |
                                  +----------+----------+
                                             |
                               stabilizzazione speaker ID
                                             |
                                      meeting_alignment
                                             |
                       ripristino testo + speaker_override compatibili
                                             |
                                   replace-on-success
```

Whisper non viene avviato in questo percorso. Il numero di interlocutori può essere cambiato prima del ricalcolo (`0` = automatico, massimo 20) e viene persistito soltanto insieme a un nuovo risultato valido.

Il precedente output viene trattato come last-known-good: diarizzazione, review, nomi speaker e stato persistiti non vengono cancellati prima dell'inferenza. Se Community-1 fallisce o il ricalcolo viene annullato, il risultato precedente rimane disponibile. Solo dopo successo `MeetingStore.set_diarization` sostituisce atomicamente le due timeline e la review e aggiorna il numero di interlocutori.

Poiché i cluster Community-1 sono locali alla singola esecuzione, un rerun può rinumerarli. UltraTranscribr confronta la nuova timeline exclusive con quella precedente tramite sovrapposizione temporale e applica un mapping uno-a-uno deterministico verso gli ID `SPEAKER_xx` esistenti. Lo stesso mapping viene applicato alla timeline regolare, mantenendo coerenti overlap, nomi e review.

Le correzioni manuali vengono riapplicate soltanto quando l'identità di provenienza Whisper è ancora compatibile. Per i nuovi interventi word-level l'identità comprende indice del segmento sorgente e range di parole; per i segmenti legacy usa timestamp e raw text.

Un rerun di una vecchia riunione priva di word timestamps migliora eventualmente il clustering Community-1, ma non può trasformarla retroattivamente in word-level: per ottenere quel dato serve una nuova trascrizione Whisper. La correzione manuale dello speaker resta comunque disponibile.

Se l'audio è stato eliminato manualmente o dalla retention automatica, la sola trascrizione non contiene informazione acustica sufficiente e il ricalcolo non viene esposto come disponibile.

## Ownership e bridge

Python mantiene stato, lifecycle, persistenza, routing e device ownership canonici.

- `FileTranscriberThread` possiede la normalizzazione dei timestamp Whisper relativi ai chunk.
- `TranscriptHistoryStore` persiste segmenti e word timing canonici.
- `SpeakerDiarizer` possiede una singola inferenza Community-1 e restituisce entrambe le timeline.
- `meeting_alignment` è un modulo di dominio puro: riconcilia timing, stabilizza ID e conserva correzioni compatibili senza dipendere da Qt, DOM o inferenza.
- `MeetingManager` possiede lifecycle iniziale/rerun e usa una sola routine `_compute_diarization`.
- `MeetingStore` possiede sidecar, override manuali, export e validazione del percorso audio persistito.
- `ApplicationService` è la boundary applicativa usata dalla UI.

Il bridge QWebChannel valida e serializza gli input `startMeetingRealtime`, `startMeetingFile`, `rerunMeetingDiarization` e `setMeetingSegmentSpeaker`; non contiene algoritmi di diarizzazione o regole di review. La UI mantiene esclusivamente stato temporaneo di presentazione.
