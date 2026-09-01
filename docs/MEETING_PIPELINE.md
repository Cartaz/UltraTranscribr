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
                                                                  |
                                                                  v
                                                           diarization
                                                                  |
                                                                  v
                                                     speaker alignment/review
```

Python mantiene stato, lifecycle, persistenza e routing canonici. Il bridge QWebChannel valida e serializza soltanto gli input `startMeetingRealtime` e `startMeetingFile`; la UI mantiene esclusivamente stato temporaneo di presentazione.
