# Impostazioni: salvataggio e applicazione

Le impostazioni globali vengono salvate con **Salva impostazioni**. Finché ci sono modifiche non salvate, l'interfaccia le segnala e impedisce di avviare un nuovo lavoro usando valori diversi da quelli mostrati. Il modello Whisper viene selezionato e salvato immediatamente; le altre modifiche pendenti restano da salvare.

Live, File e Riunione hanno una lingua propria per i nuovi lavori. All'apertura seguono il valore globale salvato; una scelta esplicita rimane valida durante notifiche, aggiornamenti e salvataggi della geometria. **Predefinita** ripristina il collegamento al valore globale. La coda conserva la lingua scelta quando si accoda il lavoro; una modifica successiva del predefinito non riscrive i lavori già configurati. La lingua mostrata per un File attivo è quella del lavoro in esecuzione.

I codici vengono normalizzati prima dell'inferenza: ` IT ` e `it-IT` diventano `it`, `en-US` diventa `en`. I codici sconosciuti vengono rifiutati. Whisper supporta anche `auto`; il percorso Qwen delle riunioni richiede una delle lingue esplicitamente supportate e non usa l'allineatore CTC inglese su testo italiano.

Il salvataggio della geometria e le modifiche esplicite sono serializzati. I valori in memoria e gli eventi della UI cambiano solo dopo la scrittura riuscita. Quando occorre riconfigurare Whisper, l'operazione esclude precaricamento e caricamento del modello; un errore di scrittura ripristina il profilo precedente. La scorciatoia della dettatura non può avviarsi durante questa transizione.

## Inventario dei 28 campi persistenti

| Campo | Modifica | Applicazione |
|---|---|---|
| `language` | Lingua predefinita; scelta distinta in ogni modalità | Lingua effettiva inviata al motore e salvata nella cronologia del nuovo lavoro |
| `model_size` | Selezione globale immediata | Modello Whisper dei nuovi Live/File; Qwen conserva il proprio modello delle riunioni |
| `audio_source` | Predefinita Live | Selezione iniziale del nuovo Live; le Riunioni hanno sorgenti proprie |
| `vad_filter` | Interruttore globale | VAD del server Whisper; la modalità musica lo disabilita per quel lavoro; Qwen mantiene la propria configurazione |
| `beam_size` | Intero 1–64 | Avvio e richieste di Whisper |
| `vad_min_silence_ms` | Intero 0–10000 | Argomento di avvio del VAD di Whisper |
| `server_port` | Intero 1–65535, compatibile con le istanze | Porta reale al caricamento successivo di Whisper |
| `backend_instances` | Intero 1–4 | Numero di istanze del pool Whisper, con porte consecutive |
| `preload_model` | Interruttore globale | All'apertura: precarica il modello selezionato se già installato |
| `channels` | Mono/stereo | Configurazione della cattura, con conversione al formato del riconoscitore |
| `chunk_ms` | Intero 100–10000 | Dimensione dei blocchi della cattura audio |
| `buffer_warn_threshold` | Intero positivo | Soglia del buffer delle nuove sessioni |
| `sink_name` | Dispositivo forzato o vuoto | Risoluzione della sorgente fisica e relativo stato; una selezione esplicita del lavoro ha precedenza |
| `sink_search_keyword` | Filtro opzionale | Ricerca automatica del microfono quando non è indicato un dispositivo esplicito |
| `live_microphone_recording` | Valore iniziale e scelta per la nuova sessione | Registrazione solo per Live da microfono; il toggle della sessione non modifica il predefinito globale |
| `dictation_activation_mode` | Push-to-talk/toggle | Servizio della scorciatoia di dettatura |
| `dictation_insertion_mode` | Progressivo/finale | Inserimento nativo della dettatura |
| `history_retention_days` | Intero 0–3650 | Conservazione della cronologia; 0 disattiva la scadenza |
| `meeting_audio_retention_days` | Intero 0–3650 | Conservazione dell'audio delle riunioni, applicata anche al salvataggio; il testo rimane |
| `window_x` | Automatica | Posizione della finestra, anche su monitor con coordinate negative |
| `window_y` | Automatica | Posizione della finestra |
| `window_width` | Automatica, minimo 1200 | Ripristino della larghezza |
| `window_height` | Automatica, minimo 800 | Ripristino dell'altezza |
| `sample_rate` | Fisso: 16000 | Formato canonico dell'audio |
| `dtype` | Fisso: float32 | Formato dei campioni nella cattura |
| `device` | Fisso: SYCL | Percorso GPU Intel; non è una scelta di fallback CPU |
| `gpu_layers` | Gestito dal motore; non editabile | Campo di compatibilità: il server non supporta una regolazione parziale dei layer |
| `compute_type` | Determinato dal modello; non editabile | Campo di compatibilità: non viene presentato come una modifica numerica realmente supportata |

I cinque campi fissi sono in sola lettura e valori diversi vengono rifiutati dalle API. Valori frazionari, infiniti, NaN e booleani non vengono interpretati come interi. Un campo numerico vuoto non diventa automaticamente zero. Se un singolo campo salvato è corrotto, viene ripristinato quel campo, conservando lingua e altre preferenze valide.

## Verifiche

La suite comprende modifica con la tastiera, scelte e interruttori reali QML, salvataggio e rilettura, reset delle sei sezioni, valori non validi, salvataggi falliti e simultanei, coda, dettatura, dispositivi forzati e conservazione su file temporanei. Tutti i test usano percorsi isolati per proteggere impostazioni e cronologia personali.

Le prove con GPU verificano la lingua nelle richieste effettive di Whisper, gli argomenti del suo processo e la provenienza del lavoro Qwen, con audio italiano già disponibile. Queste prove non misurano l'accuratezza su un nuovo corpus e non sostituiscono il collaudo di ogni periferica fisica o dei permessi interattivi del desktop.
