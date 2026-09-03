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

Python mantiene stato, lifecycle, persistenza, routing e device ownership canonici. Il bridge QWebChannel valida e serializza soltanto gli input `startMeetingRealtime` e `startMeetingFile`; la UI mantiene esclusivamente stato temporaneo di presentazione.
