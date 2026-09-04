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
                                                                  |
                                                                  v
                                              pyannote Community-1 / XPU
                                           segmentation + embeddings + VBx
                                                                  |
                                                                  v
                                             exclusive speaker diarization
                                                                  |
                                                                  v
                                                     speaker alignment/review
```

La diarizzazione usa esclusivamente `pyannote/speaker-diarization-community-1`. Se il numero di interlocutori è noto viene passato come `num_speakers`; `0` mantiene il conteggio automatico. L'output `exclusive_speaker_diarization` è quello usato per riconciliare gli speaker con i timestamp Whisper.

Le reti neurali di Community-1 vengono eseguite sul runtime condiviso PyTorch XPU della GPU Intel. UltraTranscribr non effettua fallback automatico a CPU o al precedente backend sherpa-onnx: un runtime XPU non disponibile produce un errore esplicito.

Il modello Community-1 viene scaricato una sola volta nella cache XDG dell'applicazione e poi caricato da disco. Il repository ufficiale Hugging Face è gated: prima del primo download l'utente deve accettarne le condizioni e autenticare localmente `huggingface-hub`; il token non viene salvato nelle impostazioni di UltraTranscribr.

## Ricalcolo su una Riunione già trascritta

La review espone **Ricalcola diarizzazione** finché il FLAC canonico della Riunione esiste. Il ricalcolo è una pipeline distinta solo nel lifecycle, non nell'algoritmo di diarizzazione:

```text
FLAC canonico persistito -----------+
                                    |
segmenti Whisper persistiti --------+--> Community-1 / XPU
                                             |
                                             v
                              exclusive speaker diarization
                                             |
                               stabilizzazione speaker ID
                                             |
                                      align_speakers
                                             |
                              ripristino correzioni manuali
                                             |
                                   replace-on-success
```

Whisper non viene avviato in questo percorso. Il numero di interlocutori può essere cambiato prima del ricalcolo (`0` = automatico, massimo 20) e viene persistito soltanto insieme a un nuovo risultato valido.

Il precedente output viene quindi trattato come last-known-good: diarizzazione, review, nomi speaker e stato persistiti non vengono cancellati prima dell'inferenza. Se Community-1 fallisce o il ricalcolo viene annullato, il risultato precedente rimane disponibile. Solo dopo successo `MeetingStore.set_diarization` sostituisce atomicamente diarizzazione/review e aggiorna il numero di interlocutori.

Poiché i cluster Community-1 sono locali alla singola esecuzione, un rerun può rinumerarli. UltraTranscribr confronta il nuovo timeline con quello precedente tramite sovrapposizione temporale e applica un mapping uno-a-uno deterministico verso gli ID `SPEAKER_xx` esistenti. In questo modo i nomi manuali restano associati, per quanto supportato dal nuovo clustering, allo stesso timeline vocale. Le correzioni manuali del testo vengono invece riapplicate solo quando timestamp e `raw_text` identificano ancora lo stesso segmento Whisper.

Se l'audio è stato eliminato manualmente o dalla retention automatica, la sola trascrizione non contiene informazione acustica sufficiente e il ricalcolo non viene esposto come disponibile.

## Ownership e bridge

Python mantiene stato, lifecycle, persistenza, routing e device ownership canonici. `MeetingManager` possiede sia la prima analisi sia il lifecycle di ricalcolo e condivide una sola routine `_compute_diarization`, evitando due implementazioni dell'algoritmo. `MeetingStore` è l'unico punto che valida il percorso audio persistito e aggiorna il sidecar della Riunione.

Il bridge QWebChannel valida e serializza soltanto gli input `startMeetingRealtime`, `startMeetingFile` e `rerunMeetingDiarization`; la UI mantiene esclusivamente stato temporaneo di presentazione.
