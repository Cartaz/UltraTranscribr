# Collaudo automatico sul desktop Intel — 26 ottobre 2026

Il collaudo prosegue la PR #36 dopo l'audit del 25 ottobre. La revisione Whisper scelta per questo desktop è `339f2b4e27d7c3b52f44a124a854abba507acff3`, compilata con oneAPI 2026.0 e SYCL. Il ref predefinito dell'installer resta `master`; l'installazione verificata usa l'override documentato `ULTRATRANSCRIBR_WHISPER_REF` con la SHA completa.

## Prove eseguite

| Percorso reale | Risultato |
| --- | --- |
| Riunione da file, `large-v3`, VAD, Community-1/XPU | 600 secondi di audio elaborati in 872 secondi: 164 segmenti sorgente, 224 righe di revisione, 232 turni esclusivi e 352 regolari, sei voci automatiche. Testo riconosciuto conservato nell'allineamento. PSS massima del gruppo di processi circa 3,38 GiB; nessun arresto Intel. |
| Recupero spontaneo delle ripetizioni | Nel tratto lungo si riproducono due cicli patologici: il recupero automatico viene accettato per entrambi. Restano due avvisi di audio energetico senza copertura, conservati per il riascolto. Qui il primo risultato proviene davvero dalla nuova inferenza, diversamente dalla precedente prova con risposta errata riprodotta dalla cronologia. |
| Community-1 dopo chiusura del runtime | Inferenza di 30 secondi sulla vera `xpu:0`; chiusura senza thread Python residui. |
| Dettatura automatica | Cattura reale da un ingresso virtuale con parlato preregistrato, inferenza SYCL, commit e testo finale completati. Non viene usato il microfono dell'utente per il riconoscimento. |
| Due Live contemporanee | Audio di sistema e applicazione isolata: entrambe producono testo, terminano il lavoro in coda e chiudono senza thread Python residui. |
| Cattura per applicazione | Tono di 440 Hz rilevato nell'ingresso isolato; uscita originale ripristinata e uscita temporanea eliminata. Le verifiche attendono l'assestamento asincrono di PipeWire. |
| Microfono predefinito | Apertura reale e ricezione di 16.000 campioni normalizzati; audio non salvato e non riconosciuto. |
| Registrazione Riunione con due ingressi monitor | Due toni distinti salvati nelle rispettive tracce e nella registrazione finale, mono 16 kHz. Recupero avviato durante la registrazione: nessun file attivo viene sottratto al registratore. |
| Composizione QML reale | Tutte le sei viste aperte, GPU rilevata senza sostituzioni, tray disponibile, uscita 0, nessun WebEngine e nessun thread Python residuo. Le richieste di consenso ai portali sono escluse dalla prova automatica. |
| Pacchetto candidato | Dipendenze e self-check dell'ambiente superati, con runtime SYCL e modelli locali. La build e le librerie sono copiate nel pacchetto e non dipendono dalla cartella di compilazione. |

La suite automatica completa passa **526 test**. I risultati dettagliati, le registrazioni di prova, il testo riconosciuto e i log restano locali in `.validation/`, esclusa da Git.

## Difetti trovati e corretti nel collaudo

1. **Finalizzazione Dettatura:** un unico limite pari al tempo di una richiesta poteva interrompere un insieme di richieste tutte valide, perdendo il testo finale. Il rilascio ora esaurisce la coda finita; il timeout HTTP continua a limitare ciascuna richiesta. La chiusura dell'applicazione continua a richiedere l'arresto del worker. Regressione con 24 richieste singolarmente entro il limite, ma con durata complessiva superiore al precedente limite globale.
2. **Recupero delle registrazioni attive:** il recupero in avvio poteva convertire e rimuovere un journal ancora in scrittura. Un blocco del file, valido anche fra processi, protegge creazione, scrittura e conversione. Un journal abbandonato o lasciato da un processo terminato rimane recuperabile. I piccoli file di lock restano separati dai dati audio.
3. **Registrazione dell'audio di sistema:** il percorso monitor alimentava il riconoscitore ma non il destinatario dei campioni usato dal registratore. Ora consegna anche al registratore i campioni mono normalizzati, prima della suddivisione per Whisper. Verifica sia su callback sia su due ingressi reali e FLAC finale.
4. **Microfono predefinito:** l'interrogazione senza selezione restituiva l'inventario dei dispositivi, causando un ripiego a 48 kHz. Ora viene interrogato il dispositivo di ingresso predefinito; regressione con ingresso a 44,1 kHz.
5. **Chiusura della diarizzazione:** pyannote creava un esportatore e un thread anche con metriche disabilitate. L'app disabilita le metriche prima di caricare la pipeline e chiude il provider già caricato alla fine dei worker, senza importare componenti facoltativi durante lo shutdown.

## Riproduzione

Con runtime del checkout e modelli già installati:

```bash
python tools/validate_native_meeting.py \
  --audio /percorso/registrazione.flac \
  --model-cache /percorso/cache/models \
  --output /percorso/nuova-prova --start 3600 --duration 600
python tools/smoke_app.py --native-gpu --skip-portal-prompts \
  --output /percorso/smoke-qml.json
```

La prima prova usa il controller e il percorso Riunione reali, crea copie e dati XDG isolati, riutilizza i modelli locali senza scaricarli e conserva gli hash dell'audio originale. Il directory di output deve essere nuovo. Sono presenti limiti di durata e memoria per non saturare il desktop.

## Limiti mantenuti espliciti

L'utente ha richiesto **soltanto prove automatiche**: non sono certificati il consenso interattivo ai portali, la pressione fisica della scorciatoia e l'inserimento effettivo in applicazioni esterne. Dictation Doctor conferma la disponibilità delle interfacce KDE; i test automatici dei relativi adapter non sostituiscono queste azioni reali.

Il collaudo funzionale non certifica la parità visiva esatta con Chromium, l'accuratezza di ogni parola o voce, né tutta la matrice di sistema, incluse le prove manuali e le misure di latenza della Dettatura. La finalizzazione di una coda di riconoscimento può richiedere più tempo dell'audio registrato: eliminarne il limite globale evita la perdita del testo, non rende più veloce il modello.

Questi limiti accompagnano l'integrazione delle correzioni; non vengono presentati come prove superate o come certificazione completa del prodotto.
