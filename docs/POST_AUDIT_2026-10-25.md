# Correzioni dopo l'audit — 25 ottobre 2026

La revisione di una riunione lunga riproduceva due difetti indipendenti: crescita della memoria nell'editor Chromium e deterioramento del testo durante l'allineamento fra Whisper e diarizzazione. Le correzioni proseguono il porting della PR #36, senza avviare una seconda migrazione.

## Cinque punti verificati

| Punto | Intervento e verifica |
| --- | --- |
| 1. Verificare il porting esistente | Confronto con `main` a `8cef0dc7385bcba82cb1aa41b7c04238ea208229` e con il precedente head QML `84d241bb8e48081383eb11014074a301496d0eda`. La lista QML già riciclava i delegate; il documento completo non viene più passato a QML a ogni battuta o aggiornamento del timer. |
| 2. Integrità del testo | Ordinamento stabile a parità di tempo; conservazione delle occorrenze istantanee ripetute; ricomposizione dei frammenti di token in parole intere. Se token e testo del segmento non coincidono, resta il testo completo con un avviso. Le correzioni manuali sopravvivono anche a nuovi raggruppamenti. |
| 3. Speaker isolato e ripresa errata | Nessun cambio di voce dentro una parola. Un vuoto acustico può usare la continuità solo entro 0,6 secondi, con lo stesso speaker sui due lati e senza una voce concorrente nella diarizzazione regolare o esclusiva. L'inferenza è annotata; interruzioni reali, sovrapposizioni e riprese con altra voce non vengono fuse. |
| 4. Ripetizioni e tratti mancanti | Rilevamento dei cicli estesi, divergenza fra testo e tempi, audio energetico non coperto. Un solo passaggio di recupero, in finestre di 12 secondi con un secondo di contesto e prompt azzerato. Originale e candidato restano conservati. Il candidato viene adottato solo se completo e con meno segnali di errore, senza aumentare significativamente la copertura mancante. Gli avvisi persistono separatamente dalla trascrizione e sono consultabili in Cronologia. |
| 5. Verifica sul desktop reale | Registrazione FLAC di 100 minuti e 38 secondi, revisione di 2.389 righe, riproduzione/seek, salvataggio/riapertura, confronto della memoria con Chromium e recupero di una bozza dopo SIGKILL. Originali verificati tramite SHA-256. |

L'energia audio non dimostra che ci sia parlato. I controlli individuano passaggi da riascoltare; non inventano parole mancanti e non certificano l'accuratezza del riconoscimento. I tempi servono all'allineamento e alla ricerca nell'audio; non è richiesta una produzione di sottotitoli.

## Risultati sul documento reale

- 1.379 segmenti sorgente, con 18.342 record di tempo delle parole, in parte frammenti di token.
- Nuovo allineamento senza correzioni manuali: 1.780 righe, con conservazione esatta della sequenza dei caratteri non bianchi riconosciuti. Attribuzioni automatiche ignote da 295 a 109; questo conteggio **non è una misura di accuratezza delle voci**.
- Ripristino delle correzioni: verificate tutte le 1.769 righe con interventi manuali, incluse 1.153 modifiche testuali e 1.307 override dello speaker. Testo e override conservati esattamente, anche quando cambia il raggruppamento. Le due categorie si sovrappongono.
- I fallback restano espliciti: tempi degeneri, token incompleti e ambiguità non vengono nascosti da un'attribuzione forzata.

## Memoria e persistenza

Prove nella sessione grafica reale, senza sostituire il rilevamento GPU. Misura PSS dell'intero gruppo di processi, così le pagine condivise di Chromium non vengono contate più volte. Confronto dell'editor con riproduzione disattivata per entrambi i frontend:

| Frontend | Cicli completati | PSS osservata dopo i cicli | Esito |
| --- | ---: | --- | --- |
| Chromium, `main` di riferimento | 2 | 1.157 MiB, poi 1.661 MiB | Durante il terzo ciclo scatta la protezione della prova a 1,8 miliardi di byte PSS; arresto preventivo prima di esaurire la memoria del desktop |
| QML, confronto iniziale | 16 | 285–294 MiB | Tutti i salvataggi verificati |
| QML, versione finale | 64 | 289–307 MiB; ultimi 16 cicli: 305–307 MiB | Tutti i salvataggi verificati; 32–33 thread, incluso il campionatore |

La prova QML separata con decoder FLAC, riproduzione muta e seek a 120 secondi completa altri 16 cicli; PSS finale circa 364 MiB e 53 thread. Nessun modulo WebEngine e nessun thread Python residuo dopo la chiusura. Il confronto Chromium non completa 16 cicli: non viene presentato come prova superata.

Le bozze vengono protette in un piccolo file atomico separato, con una revisione che impedisce a scritture vecchie di ripristinare testo annullato. Una nuova esecuzione ripristina soltanto bozze che corrispondono ancora al segmento e al suo testo di partenza. Le bozze con riferimenti cambiati restano consultabili e copiabili, senza essere applicate ad altre frasi. Un file di bozze danneggiato lascia accessibile il testo confermato.

Il processo di prova è stato terminato con SIGKILL dopo la conferma della scrittura della bozza: un nuovo processo ha recuperato il testo esatto. È verificato anche il cambio immediato di riunione dopo l'annullamento. La protezione è periodica: non garantisce le battute non ancora arrivate su disco prima dell'arresto.

## Inferenza Intel: esito distinto dall'editor

Sul desktop con Intel Arc Meteor Lake, driver `xe`, Python 3.14, PySide6 6.11.2 e oneAPI 2026.0:

1. Il runtime Whisper installato restituisce `UR_RESULT_ERROR_UNKNOWN` e `Error OP GET_ROWS`; il registro del kernel segnala un timeout della coda GPU. Il controllo elementare PyTorch XPU passa. Non è quindi corretto attribuire il guasto al solo consumo della UI o dichiarare inutilizzabile tutta la GPU.
2. Disabilitare VMM per il solo processo di prova non dà un risultato verificato entro il limite breve. Non è adottato come rimedio.
3. Una build separata del sorgente Whisper `339f2b4e27d7c3b52f44a124a854abba507acff3`, con SYCL e lo stesso compilatore, trascrive realmente 15 secondi con `large-v3`; integrità del testo e allineamento verificati. La prima richiesta con limite di 50 secondi scade; quella successiva con limite adeguato termina correttamente. Non è un fallback CPU.
4. Il recupero viene provato su 18,4 secondi del tratto patologico. Si riproduce **la risposta errata già registrata** come primo risultato; le due richieste successive sono inferenze SYCL reali sull'audio corrispondente. Il candidato viene accettato, i segnali di errore rilevati spariscono e la risposta originale resta identica. Questo prova il percorso di recupero, non l'insorgenza spontanea del ciclo nella nuova build né l'esattezza di ogni parola recuperata.

I messaggi d'errore conservano i simboli diagnostici e il percorso del log senza riportare frasi della trascrizione. Un processo morto non viene ritentato fino a perdere la diagnosi iniziale.

Il programma installato, il driver e le impostazioni globali non sono stati cambiati. L'installer continua a seguire il ref già configurabile mediante `ULTRATRANSCRIBR_WHISPER_REF`; non è stato modificato il suo default `master`. La revisione di confronto è una configurazione verificata per questi campioni, non una certificazione generale del runtime.

## Verifiche riproducibili e limiti

- Suite completa sul desktop: **520 test passati**; prima delle correzioni di questo audit: 481.
- `qmllint`, compilazione Python, controllo del diff e lint sulle parti modificate passano. I test coprono tempi uguali, frammenti di token, copertura mancante, interruzioni vere, sovrapposizioni, cambio voce alla ripresa, recupero incompleto o fallito, compatibilità dei file e concorrenza delle bozze.
- Il tool seguente usa copie isolate e campiona memoria e thread. Non avvia inferenza o registrazione. Sostituire i percorsi con gli input locali:

```bash
python tools/validate_meeting_review.py \
  --history /percorso/trascrizione.json \
  --meeting /percorso/riunione.json \
  --audio /percorso/registrazione.flac \
  --output /percorso/prova-qml --cycles 64 --skip-playback
# Per verificare anche la riproduzione, omettere --skip-playback.
# Per il riferimento Chromium, usare --frontend web --source-root /percorso/baseline.
```

`--checkpoint-only` conferma su disco la bozza prima di attendere l'arresto; `--reopen` verifica il recupero in un nuovo processo. Usare una directory nuova per ogni prova di arresto. La protezione di memoria interrompe il test a 1,8 miliardi di byte PSS.

Trascrizioni, audio, screenshot, log completi e risultati dettagliati rimangono locali in `.validation/`, esclusa da Git. Nessun dato della riunione viene caricato nella PR.

La PR resta draft per i limiti del porting originale: parità visiva esatta ancora aperta e matrice completa Live/Dettatura/hotkey/routing/Demucs/Community-1 da verificare separatamente. Le prove qui riportate coprono questa roadmap dell'audit; non sostituiscono l'intera accettazione del prodotto, non dimostrano assenza di ogni possibile OOM e non correggono da sole il guasto del motore installato.
