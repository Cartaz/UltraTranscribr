# Batch Riunioni

La modalità **Riunione → Da registrazione** accetta più file audio/video e li elabora tramite una coda FIFO sequenziale.

## Perché la coda è sequenziale

Ogni registrazione usa la pipeline Meeting completa già esistente:

```text
media -> FLAC mono 16 kHz -> Whisper/SYCL -> Community-1/XPU -> allineamento speaker -> review
```

UltraTranscribr non esegue più riunioni in parallelo. In questo modo Whisper e Community-1 non competono per GPU/RAM e il batch resta utilizzabile anche su sistemi con memoria limitata.

## Configurazione per registrazione

I campi **Lingua predefinita** e **Interlocutori predefiniti** servono solo come valori iniziali quando vengono selezionati i file. Prima di avviare il batch, la UI mostra una riga per ogni registrazione e permette di cambiare separatamente:

- lingua;
- numero di interlocutori (`0` = rilevamento automatico, massimo `20`).

Questi valori vengono congelati nel relativo job quando il batch viene avviato. È quindi possibile elaborare nello stesso batch, per esempio, una riunione con 5 interlocutori, una con 4 e una con 9 senza creare code separate.

La richiesta viene validata interamente prima di modificare la coda: un file mancante o una configurazione non valida non può lasciare un batch parzialmente accodato.

## Comportamento

- si possono selezionare più registrazioni con un'unica finestra file;
- lingua e numero di interlocutori possono essere configurati separatamente per ogni registrazione prima dell'avvio;
- il modello Whisper resta quello configurato nell'applicazione e le impostazioni backend sono bloccate finché la coda è attiva;
- ogni job mostra la propria configurazione, la fase, il progresso Whisper e il progresso diarizzazione;
- al completamento la riunione viene salvata nell'Archivio senza aprire automaticamente la review;
- se un job fallisce, l'errore resta visibile nella coda e il job successivo viene avviato comunque;
- **Annulla coda** interrompe la riunione attiva e marca come annullate quelle ancora in attesa;
- **Pulisci completate** rimuove dalla sola vista della coda i job terminali; non elimina le riunioni archiviate;
- la coda è intenzionalmente temporanea e non viene ripristinata dopo il riavvio dell'applicazione.

Live, File, Dettatura, ricalcolo della diarizzazione e modifiche alle impostazioni/backend sono mutuamente esclusivi con una coda Riunioni attiva. La review e l'Archivio restano consultabili mentre il batch lavora.

## Ownership

`core/meeting_batch.py` possiede esclusivamente scheduling FIFO e stato transitorio dei job. `MeetingManager` resta l'unico proprietario della pipeline di una singola riunione. `ApplicationService` normalizza i valori per-file, applica le regole di esclusività tra workflow e possiede il lifecycle della coda; il bridge QWebChannel espone soltanto valori serializzati e comandi mirati.
