# UltraTranscribr 5.5.0 — Piano completo di miglioramento

**Stato:** APPROVATO dall'utente il 29/10/2026. Stato dell'implementazione, verifiche e limiti in [UX_IMPLEMENTATION_2026-10-29.md](UX_IMPLEMENTATION_2026-10-29.md).
**Origine:** commento Live trascritto il 29/10/2026 (271 righe) e screenshot "UI Live.png", "UI File.png", "UI Riunione 1.png", "UI Riunione 2.png" allegati alla conversazione.  
**Destinatari:** agenti di sviluppo che dovranno esaminare il repository, realizzare, verificare e documentare le modifiche.  
**Ambito:** tutti i flussi Live, File, Riunioni, Cronologia, Impostazioni e Log.  
**Vincolo:** preservare i workflow esistenti e non dichiarare verificati risultati non misurati. Le descrizioni degli screenshot e della trascrizione sono evidenza dell'esperienza utente, non conferma della causa tecnica dei bug.

## Obiettivi

1. **Ridisegnare l'interfaccia rendendola molto più compatta**: eliminare titoli ripetitivi, informazioni superflue e sottotitoli permanenti.
2. **Correggere i problemi che compromettono l'uso**: scrolling Live, accumulo e metrica del buffer, riproduzione originale, autosalvataggio e Undo/Redo.
3. **Semplificare la configurazione**: pochi modelli centrati sull'accuratezza, cronologia riconoscibile, revisione efficiente.

L'obiettivo non è soltanto ridurre padding: il testo e le operazioni principali devono prevalere su informazioni tecniche e decorazioni.

## 1. Principi comuni a tutta la UI

| Elemento | Modifica approvata |
| --- | --- |
| Titoli | Eliminare intestazioni che ripetono il nome della pagina nel menu laterale. |
| Intestazioni interne | Una sola intestazione informativa per area, niente catene di titoli/sottotitoli. |
| Descrizioni | Portare nei tooltip le spiegazioni non necessarie alla normale operazione. |
| Lingue | Mostrare Italiano, Inglese ecc.; conservare internamente i codici it, en ecc. |
| Controlli | Mettere sulla stessa riga quelli collegati logicamente. |
| Metadati | Visualizzare solo i dati utili al lavoro in corso; dettagli tecnici nei log o in viste espandibili. |
| Pulsanti | Nomi comprensibili, semantica verificata; evitare termini ambigui. |
| Scroll | Bar e segnali di scorrimento visibili quando contenuti non sono immediatamente accessibili. |
| Responsive | Nessuna funzione importante deve essere tagliata, nascosta o irraggiungibile. |

**Linguaggio visivo da mantenere:** Dark Neumorphism con superficie rgb(20,20,20), accento #FF6600, grigi, testo leggibile, profondità sottile e gerarchia data da spaziatura e tipografia. L'arancione esprime selezione/stato, non un livello addizionale di titoli. Riutilizzare componenti e token di Theme.qml invece di duplicare effetti.

**Obiettivo misurabile da validare, non risultato già ottenuto:** ridurre indicativamente del 25–35% l'altezza dei moduli di configurazione; puntare a una sola intestazione per area e nessun controllo non raggiungibile. Verificare con screenshot, non con impressioni.

## 2. Live — criticità prioritarie

### 2.1 Acquisizione e avvio

- Rimuovere "TRASCRIZIONE LIVE" e "INGRESSO" (ridondanti).
- Mantenere la selezione **Audio di sistema / Applicazione / Microfono**.
- Mantenere l'etichetta **Sorgente audio**.
- Accorpare **Dispositivo** e **Lingua** nella stessa riga.
- Spostare la spiegazione della modalità "Rilevamento automatico" nel tooltip della selezione dispositivo.
- Usare un menu lingua con nomi completi e codici backend corretti (es. Italiano -> it).
- Rimuovere dal layout ordinario la riga "Disponibile · automatico · default"; segnalare comunque accanto al controllo eventuali errori o indisponibilità reali.
- Tenere "Salva registrazione" + toggle, ma togliere il sottotitolo "Solo Microfono. Default: OFF...".
- Rinominare **Aggiungi sessione** in **Inizia registrazione**.

### 2.2 Sessioni live

- Sostituire "SESSIONI LIVE — Trascrizioni indipendenti" con **Trascrizioni in corso**.
- Rimuovere il sottotitolo "1 sessioni attive": il numero è desumibile dalle card.
- Eliminare dalla vista primaria UUID, codici temporali, "default", modello, lingua, coda in ms e "routing diretto", quando non utili.
- Mostrare soltanto una breve etichetta intelligibile della sorgente per distinguere più sessioni, poi il testo trascritto.
- Dedicare la maggior parte della superficie della card al testo.
- Conservare **Copia**, **Completa buffer**, **Ferma**, **Rimuovi**; conservare **Completa tutte** e **Ferma tutte**.
- Verificare la semantica reale di "Completa buffer": se termina l'acquisizione drenando e trascrivendo il residuo, la denominazione consigliata è **Termina e completa**, distinta da una fermata immediata.
- Ogni sessione deve avere scorrimento autonomo e accessibilità da tastiera. L'area trascrizione deve essere visibile senza dover scorrere costantemente l'intera pagina principale.

### 2.3 Bug e diagnostica

**LIV-01 — Autoscroll.** Ogni nuovo chunk riporta attualmente la visualizzazione in alto (problema riferito dall'utente). Implementare modalità "segui ultimo chunk" che mantiene in vista il testo più recente. Se l'utente scorre manualmente verso l'alto, sospendere il follow e offrire **Torna al live**. Non perdere la selezione del testo o il focus di un controllo.

**LIV-02 — Buffer >100%.** Nel feedback compaiono 110%, 114%, 125% e fino a **484%**, insieme a lentezza percepita. Verificare che cosa misura la percentuale, capacità reale, produzione/consumo chunk, durata audio in attesa, latenze, scheduler/backpressure e preservazione dell'audio. Non correggere il bug limitando semplicemente a 100% la rappresentazione grafica.

**LIV-03 — "Coda 0 ms" incoerente.** Chiarire se "coda" e buffer misurano grandezze differenti. Se la misura è errata correggerla; se è poco utile toglierla dalla vista principale mantenendola nei log. Non supporre che 0 ms rappresenti lo stesso valore del buffer senza verifiche.

**Problema prestazionale aggiuntivo:** durante la registrazione l'utente riferisce un rallentamento che collega all'alimentazione del computer; eseguire prove distinte con alimentatore collegato e in batteria prima di attribuire il problema a UltraTranscribr.

**Accettazione Live:** con dimensioni finestra simili agli screenshot (circa 1650x930), testo e comandi principali leggibili senza navigazione verticale continua; nuovi chunk seguiti automaticamente; scroll manuale rispettato; misure buffer/coda affidabili e nessuna perdita silenziosa sotto carico.

## 3. File — riorganizzazione

### 3.1 Layout

Organizzare tre sole aree coerenti, evitando titoli ridondanti e gerarchie discordanti:

1. **Selezione file**: file audio/video, sfoglia multipli, lingua, Modalità musica, Isola voce, Accoda/Ferma.
2. **Coda file**: elementi, avanzamento del file in esecuzione, progresso complessivo e stato.
3. **Trascrizione file**: testo risultante, Copia, Pulisci.

- Eliminare le etichette supplementari "TRASCRIZIONE FILE", "MEDIA", "BATCH", "SESSIONE", "OUTPUT" nella forma attuale.
- Mantenere selezione file e caricamento multiplo.
- Lingue in menu con nomi completi.
- Mettere **Modalità musica** e **Isola voce** su una riga, con toggle; rimuovere sottotitoli permanenti.
- Rimuovere il pannello autonomo **Elaborazione file** (status/model/lingua/file duplicati).
- Integrare stato e avanzamento dentro **Coda file**.
- Conservare gestione coda: pulisci completati, annulla coda, arresto.
- Uniformare dimensioni, tipografia, spazi e colori delle tre aree.
- Distinguere progresso **file corrente** da progresso **intera coda**; se una fase non permette stima attendibile, usare stato indeterminato invece di percentuali fittizie.

**Accettazione:** anche con file multipli è immediatamente chiaro quale file viene lavorato e cosa resta; nessuna perdita delle funzionalità batch.

## 4. Riunioni — acquisizione, archivio e revisione

### 4.1 Acquisizione

Ridurre la sommità a due pannelli compatti:

- **Acquisisci e analizza**: modalità in tempo reale/da registrazione, sorgenti o file, motore, lingua, interlocutori predefiniti, avvio.
- **Pipeline riunione**: stato ed effettivo progresso delle fasi di trascrizione e diarizzazione.

Requisiti:
- Rimuovere le molteplici intestazioni "Riunione"; mantenere **Acquisisci e analizza**.
- Conservare scelta in tempo reale / da registrazione.
- Nel flusso realtime conservare sorgenti **microfono / sistema / applicazione** e selezione automatica.
- Spostare nel tooltip di "Sorgenti" la spiegazione sulla combinazione fino a 8 sorgenti.
- Mantenere "Motore riunioni" ma rimuovere spiegazioni ridondanti come "Qwen pronto..." dal layout; errori/indisponibilità reali devono restare visibili.
- Conservare **Verifica/Prepara modelli riunioni**.
- Menu delle lingue con etichette complete.
- Conservare interlocutori predefiniti, compreso **0 = rilevamento automatico**.
- Conservare pulsanti per analizzare registrazione / avviare riunione e per interrompere/annullare secondo stato reale.
- Mantenere i progressi separati di trascrizione e diarizzazione, ma con meno ingombro verticale.
- Rendere più in alto e visibile l'archivio delle riunioni recenti.

### 4.2 Riunioni recenti

- Su desktop **due card per riga** anziché una riga a tutta larghezza; su finestre strette tornare a una colonna.
- Card leggermente più alte, altezza coerente, testo preview max poche righe, ellissi senza fuoriuscite/overflow.
- Mostrare titolo informativo, data/ora, stato utile e breve anteprima; conservare azione elimina con conferma.
- Indicare chiaramente quale riunione è selezionata.
- **Quando si clicca una card, scorrere automaticamente e delicatamente la pagina fino alla sezione Revisione/Interventi**, senza togliere il focus della tastiera a un editor attivo.
- Conservare selezione nell'aggiornamento archivio; per molti risultati usare modelli/virtualizzazione.

**Accettazione:** selezionare una riunione rende evidente e visibile l'editor relativo; nessuna card tagliata; archivio più denso.

### 4.3 Audio originale nell'editor

**REV-01 — Bug da verificare.** L'utente riferisce che il player della revisione riproduce audio di qualità degradata, forse il derivato a 16 kHz preparato per il riconoscimento, invece del file originale. Verificare il percorso reale: non dichiarare certa la causa finché non esaminata.

**Requisito approvato:** l'ascolto in revisione deve utilizzare la **registrazione originale**, non una versione modificata per Whisper/Qwen/diarizzazione.

- Traccia A: audio originale per playback.
- Traccia B: eventuali resampling/normalizzazioni/elaborazioni per STT e diarizzazione.
- Conservare un riferimento persistente al file originale verificandone esistenza e integrità.
- Timeline e timestamp devono essere verificati rispetto all'audio originale.
- Supportare play/pausa, ricerca temporale e ripresa.
- Rispettare conservazione ed eliminazione dell'audio.
- Se l'originale non esiste più, segnalare il limite e non fingere di averne ricostruito la qualità.
- L'utente deve sentire la registrazione come realmente acquisita, anche se ai modelli viene fornito un derivato.

### 4.4 Esportazione e diarizzazione

Conservare:
- **Esporta TXT**.
- **Esporta SRT**.
- **Elimina audio**.
- **Numero interlocutori per ricalcolo**.
- **Ricalcola diarizzazione**.

Rimuovere il pulsante **Esporta VTT** e, come richiesto, la relativa funzione, **dopo audit delle dipendenze/compatibilità**. Non eliminare inavvertitamente percorsi comuni di esportazione.

Spostare nel tooltip del pulsante "Ricalcola diarizzazione" la spiegazione "Riusa l'audio e il testo..." e togliere il paragrafo permanente.

Il ricalcolo deve preservare trascrizioni, modifiche di testo, nomi e assegnazioni manuali ove compatibili. Gestire esplicitamente i conflitti di speaker quando cambiano le segmentazioni.

### 4.5 Interlocutori

Nel caso mostrato ci sono **9 interlocutori**, ma solo 5 visibili e nessun segnale di scroll.

- Introdurre barra/indicatore di scorrimento chiaramente visibile.
- Intestazione **Interlocutori (9)** o numero dinamico.
- Tutti raggiungibili e rinominabili da mouse e tastiera.
- Rinominare aggiorna la visualizzazione degli interventi.
- Gli ID tecnici speaker rimangono stabili anche cambiando etichette.

### 4.6 Editor: salvataggio automatico + Undo/Redo

**REV-02, REV-03 — priorità P0**.

- Qualsiasi modifica al testo di ogni intervento deve salvarsi automaticamente; niente necessità di premere "Salva correzione" o "Salva tutto".
- Il cambio speaker deve rimanere persistente in automatico e usare una strategia coerente.
- **Ctrl+Z** annulla; **Ctrl+Shift+Z** o **Ctrl+Y** ripristina.
- Undo e Redo devono funzionare anche dopo che l'autosalvataggio è avvenuto.
- Usare originale immutabile + versione revisionata distinta; un edit non deve cancellare l'originale.
- La pila di modifiche deve appartenere al documento/canonical state, non a una card QML effimera, soprattutto con delegate riciclati.
- Indicare **Salvataggio in corso / Tutte le modifiche salvate / Errore di salvataggio**; "Salvato" soltanto su conferma del supporto persistente.
- Strategia di partenza: debounce breve durante digitazione, flush su uscita dal campo e chiusura controllata, scritture atomiche/versionamento; valutare journal persistente per crash improvviso.
- Il fallimento di persistenza non deve scartare le modifiche né mostrare un falso successo.

**Accettazione:** modificare decine di interventi, salvare automaticamente, riavviare e ritrovare tutte le modifiche confermate; annullare/ripristinare correttamente; simulare crash/failure DB e verificare nessuna corruzione e feedback chiaro. La perdita dell'ultima digitazione non ancora confermata come salvata va trattata secondo semantica dichiarata.

### 4.7 Seguito dell'audio con scorrimento sincronizzato

**REV-05 — nuova funzione richiesta:**
- Player espone posizione reale corrente.
- Identificare intervento/i con intervallo temporale che contiene il playhead.
- Evidenziare segmento attivo e scrollare solo se non visibile (follow discreto).
- Il cambio intervento segue l'avanzamento audio.
- Cliccare un timestamp porta l'audio a quel punto.
- Con voci sovrapposte, più segmenti possono essere contemporaneamente attivi.
- Se l'utente scorre volontariamente o sta correggendo testo altrove, sospendere l'autofollow: l'audio non deve rubare focus o annullare selezioni.
- Fornire comando per **Riprendi sincronizzazione**.
- Una posizione esemplificativa di 00:42 evidenzia l'intervento relativo, e passando a 00:58 evidenzia il successivo.

Per l'implementazione, preferire informazioni temporali dal backend e segnali Qt; la QML gestisce highlight e navigazione. Misurare la frequenza degli aggiornamenti per evitare scroll e layout jitter.

### 4.8 Dieci concept UI richiesti (deliverable separato)

La richiesta finale della trascrizione è **cinque varianti solo UI (A1–A5) + cinque varianti con le medesime UI e sincronizzazione audio (B1–B5)**. Le descrizioni che seguono costituiscono il brief approvato; i dieci mockup definitivi **non sono ancora stati generati**.

Tutti i mockup devono avere la **stessa** trascrizione fittizia, durata audio, intervalli e speaker, dimensioni finestra e Dark Neumorphism. Devono rendere visibili timestamp, scelta speaker, testo modificabile, stato autosave, scrolling. Le versioni B aggiungono playhead, evidenziazione attivo, follow, seek via timestamp, pausa follow e sovrapposizioni.

| Coppia | A: solo nuova UI | B: stessa UI + follow audio |
| --- | --- | --- |
| A1/B1: **Lista compatta** | Righe essenziali, timestamp a sinistra, speaker e testo affiancati; alta densità. | Riga attualmente riprodotta evidenziata e portata in vista. |
| A2/B2: **Editor a due colonne** | Sinistra indice degli interventi; destra editor ampio del selezionato. | Selezione segue il tempo audio, ma non interrompe una correzione in corso. |
| A3/B3: **Documento continuo** | Trascrizione come documento con speaker e timestamp inline. | Highlight del passaggio letto, con scroll morbido e minimo. |
| A4/B4: **Timeline degli speaker** | Segmenti distribuiti nel tempo, speaker e sovrapposizioni visibili. | Playhead che avanza e mantiene in vista gli eventi correnti. |
| A5/B5: **Revisione guidata** | Intervento attuale grande, precedente e successivo in secondo piano. | Card principale segue la riproduzione con transizioni contenute. |

Valutare soprattutto **A1/B1**, **A2/B2**, **A3/B3**. Non scegliere prematuramente: presentare tutte e dieci e prendere una decisione progettuale a confronto. La UI dovrà comunque essere più compatta di quella attuale.

## 5. Cronologia e Recovery

### Nuovo sistema di titoli

Il problema è la scarsa identificabilità di voci come "default", nomi tecnici d'uscita audio o "recovery_live_1787249127".

Ogni sessione deve avere:
- **ID tecnico stabile, invisibile**.
- **Titolo leggibile, modificabile dall'utente**.
- **Titolo predefinito automatico** quando non viene assegnato un titolo.

Esempi illustrativi, da generare soltanto con dati reali:
- default -> "Microfono · 29/10/2026 19:14".
- Sorgente di riproduzione -> "Audio di sistema · 29/10/2026 18:40".
- Applicazione -> "Firefox · 29/10/2026 17:22".
- recovery_live_1787249127 -> "Microfono · 20/08/2026 14:45 · Recuperata".
- File -> "Collegio docenti.mp3 · 23/10/2026".

Attività:
- Aggiungere/rendere evidente la rinomina nelle sessioni Live, File e Cronologia.
- Propagare il medesimo titolo in elenco e dettagli.
- Mantenere identificatori tecnici per riferimenti e migrazioni.
- Preservare marker e operazioni Recovery, distinguendo audio recuperabile da registrazione completa.
- Mostrare lingua come nome completo, ridurre stati ridondanti e compattare metadati.
- Non inferire sorgenti e date senza dati: per record legacy, fallback esplicito non ingannevole.
- Non perdere collegamenti esistenti durante migrazioni.

**Accettazione:** sessioni distinguibili, titoli rinominabili e persistenti; recovery sempre utilizzabile e navigabile.

## 6. Impostazioni e modelli

### 6.1 Modelli da mantenere nella configurazione ordinaria

L'utente privilegia **accuratezza rispetto alla velocità**.

- **Trascrizioni monovoce (Live, File, dettatura dove compatibile): Whisper Large v3.**
- **Riunioni: Qwen + Community-1** per testo/diarizzazione. *Verificare modelli e pipeline effettivi prima di intervenire.* Il README attuale del repository cita **Qwen3-ASR-1.7B** e **pyannote Community-1**; non considerare la trascrizione spontanea una specifica più precisa del repository.
- Rimuovere dalla UI scelta, download e installazione di modelli Whisper alternativi come Turbo/Medium, una volta verificati eventuali impatti su flussi dipendenti e migrazione.
- Mantenere preparazione, verifica e stato dei soli modelli richiesti.
- Allineare pulsanti modello (verifica/elimina) vicino all'informazione relativa, evitando layout allungati.
- Non cancellare automaticamente download, dati e installazioni degli utenti al momento della migrazione.

### 6.2 Impostazioni avanzate: eliminazione condizionata

L'utente autorizza l'eventuale eliminazione della tab **Avanzate** **solo dopo** aver dimostrato che le regolazioni integrate nel backend sono adeguate all'accuratezza richiesta.

Audit richiesto:
- Whisper: beam search, temperature, prompt, gestione contesto/ripetizioni.
- VAD, chunking, silenzi, confini e segmentazione.
- Gestione lingua e normalizzazione del testo.
- Qwen: opzioni realmente supportate e utilizzate dal codice corrente.
- Community-1: diarizzazione, numero speaker, overlap, allineamenti, finestre e assegnazione.
- Dataset rappresentativi italiano/inglese; misure WER/CER, errori speaker e regressioni significative.
- Test di performance necessari a non compromettere la Live.

Solo a risultati validati fissare i parametri e rimuovere l'interfaccia avanzata non necessaria. **Non esiste un preset universalmente ottimo**: evitare di dichiararlo senza prove.

### 6.3 Opzioni da mantenere

- Conservazione cronologia e recovery.
- Dettatura / inserimento globale.
- Push-to-Talk: esplicitamente non ancora testato; inserirlo in verifica successiva, non dichiararlo funzionante senza provarlo.
- Compattazione generale delle impostazioni senza spezzare comportamenti validi.

## 7. Log

- Conservare schermata e funzionalità (già ritenute soddisfacenti).
- Allineare soltanto i componenti visivi condivisi se necessario.
- Mantenere nel log i dettagli diagnostici di buffer, latenza, pipeline, audio e persistenza, invece di mostrarli permanentemente nell'interfaccia ordinaria.

## 8. Architettura e proprietà dello stato

Standard di lavoro previsto per il progetto, salvo architettura esistente deliberata da preservare:
- **Python core**: acquisizione, buffer, scheduling, naming, servizi di revisione, modello di segmenti, autosave, recovery, persistenza e conversioni.
- **AppController**: coordinamento e lifecycle, non duplicazione delle regole dei servizi.
- **Qt adapter / modelli**: Property/Signal/Slot tipizzati e QAbstractListModel per collezioni non banali.
- **QML**: soli layout, animazioni, controlli, focus, evidenziazione e stato transitorio della presentazione.
- **Theme.qml** e componenti riutilizzabili: Dark Neumorphism consistente.
- Main soltanto wiring e lifecycle.
- Grandi liste: ListView/TableView con delegate leggeri e reuseItems quando opportuno; niente array JS duplicati come stato canonico.
- Nessun blocco del thread GUI; shutdown deterministico.
- Non migrare a WebEngine/HTML/JS; non riscrivere logica domain sana per motivi estetici.

### Modello logico richiesto per gli interventi

- ID stabile del segmento.
- Start e end rispetto alla timeline originale.
- Speaker ID stabile.
- Testo originale immutabile.
- Testo revisionato distinto.
- Revisione/versione per gestione conflitti e Undo/Redo.
- Stato salvataggio reale (in attesa, persistito, fallito).
- Supporto a segmenti temporalmente sovrapposti.

Riutilizzare la persistenza esistente quando supporta questi requisiti; non introdurre un database o una nuova astrazione senza necessità reale.

## 9. Roadmap di implementazione ordinata

### Fase 0 — Audit e baseline (prerequisito)

1. Inventario moduli, controller, servizi, modelli, QML, persistenza, native integration, concurrency e test.
2. Mappare fonte di verità per sessioni e revisioni.
3. Riprodurre comportamenti segnalati.
4. Raccogliere screenshot, log, tempi/metriche e baseline test.
5. Verificare flussi legacy prima di modificare dati persistenti.

**Deliverable:** mappa dei componenti e test di partenza, problemi riproducibili, dipendenze tecniche note.

### Fase 1 — Affidabilità (P0)

1. Correggere autoscroll Live.
2. Analizzare e correggere buffer/backpressure e indicatori incoerenti.
3. Separare playback originale da audio elaborato.
4. Autosalvataggio correzioni speaker/testo realmente persistente.
5. Undo/Redo corretto anche dopo autosave.
6. Gestire failure storage, crash, riavvio, recovery.

**Deliverable:** protezione verificabile delle correzioni e stabilità delle sessioni principali.

### Fase 2 — Componenti + UI compatta Live/File (P1)

1. Centralizzare componenti QML e token, ridurre titoli, tooltip coerenti.
2. Selettori lingue con nomi completi.
3. Layout Live con trascrizione dominante.
4. Layout File a tre aree con avanzamento nella coda.
5. Screenshot comparison e verifica responsive.

**Deliverable:** Live e File completi e usabili con meno ingombro e nessuna regressione.

### Fase 3 — Riunioni e revisione (P1)

1. Generare e presentare **tutti e 10** i mockup A1–A5/B1–B5.
2. Scegliere il design a confronto.
3. Acquisizione e pipeline compatte.
4. Archivio riunioni a 2 colonne + navigazione automatica all'editor.
5. Interlocutori scorrevoli e visibili.
6. Editor integrato ad autosave/Undo.
7. Audio-testo sincronizzati con seek/follow/overlap e sospensione dello scroll.
8. Preservare dati e revisioni durante ricalcolo speaker.

**Deliverable:** editor efficiente per registrazioni lunghe e multi-speaker.

### Fase 4 — Cronologia e impostazioni (P1/P2)

1. Titoli automatici leggibili e rinomina.
2. Migrazione/recovery compatibili.
3. Compattazione della cronologia.
4. Gestione modelli ridotta ai percorsi supportati.
5. Audit dell'accuratezza prima di eliminare Avanzate.
6. Rimuovere VTT solo dopo verifiche d'impatto.

**Deliverable:** workflow più semplici, opzioni allineate ai modelli realmente usati.

### Fase 5 — Regressione e rilascio (obbligatorio)

1. Test core, controller, settings, adapter/modelli, QML/offscreen.
2. Test reali acquisizione, complete/drain, stop, recovery, ascolto, edit e riavvio.
3. Test stress multisingola sorgente, multi-sessione, batch, diarizzazione e speaker overlap.
4. Controlli focus da tastiera, tooltip, scrollbar, contrasto, dimensioni responsive.
5. Screenshot comparativi e misurazioni di CPU, GPU, latenza e PSS Linux.
6. Compileall, pytest, ruff se configurato, QML lint/load, shader verification se presenti.
7. Review strategica: ownership, duplication, layer leaks, workaround e performance.

**Deliverable:** report con test realmente eseguiti, risultati osservati, regressioni e lavoro incompleto dichiarato esplicitamente.

## 10. Registro operativo / ID issue

| ID | Attività | Priorità | Criterio base |
| --- | --- | --- | --- |
| LIV-01 | Autoscroll ultimo chunk | P0 | Mai salto involontario all'inizio |
| LIV-02 | Buffer e backpressure | P0 | Accumulo misurato/gestito e nessuna perdita silenziosa |
| LIV-03 | Metriche coda coerenti | P0 | Valori spiegabili e corretti |
| REV-01 | Audio originale in player | P0 | Riproduce realmente la sorgente originale |
| REV-02 | Autosalvataggio testo/speaker | P0 | Modifiche persistenti dopo riavvio |
| REV-03 | Undo/Redo | P0 | Annullamento e ripristino anche dopo autosave |
| UI-01 | Gerarchia titoli | P1 | Eliminazione ripetizioni |
| UI-02 | Tooltip | P1 | Spiegazioni disponibili senza ingombro |
| UI-03 | Menu lingua | P1 | Nomi leggibili, codici validi |
| UI-04 | Layout responsive | P1 | Zero controlli inaccessibili |
| LIV-04 | Compattazione Live | P1 | Trascrizione in primo piano |
| LIV-05 | Azioni sessione | P1 | Nomi e comportamento non ambigui |
| FIL-01 | Compattazione File | P1 | Tre aree coerenti |
| FIL-02 | Progresso nella coda | P1 | Stato e avanzamento per file/totale |
| MEET-01 | Acquisizione compatta | P1 | Controlli principali immediati |
| MEET-02 | Archivio a due colonne | P1 | Card leggibili e responsive |
| MEET-03 | Focus automatico revisione | P1 | Selezione porta all'editor |
| MEET-04 | Scroll interlocutori | P1 | Tutti gli speaker raggiungibili |
| REV-04 | 10 mockup revisione | P1 | A1–A5 e B1–B5 confrontabili |
| REV-05 | Follow audio-testo | P1 | Interventi sincronizzati, seek e overlap |
| HIST-01 | Titoli automatici | P1 | Niente nomi tecnici incomprensibili |
| HIST-02 | Rinomina | P1 | Titoli modificabili e persistenti |
| SET-01 | Modelli supportati | P2 | Configurazione semplificata |
| SET-02 | Audit accuratezza | P2 | Parametri valutati con test |
| SET-03 | Rimozione eventuale Avanzate | P2 | Solo dopo validazione |
| EXP-01 | Rimozione VTT | P2 | Nessuna dipendenza residua |
| TEST-01 | Push-to-Talk | P2 | Workflow verificato |
| LOG-01 | Preservazione log | P2 | Nessuna regressione |

## 11. Piano di test / criteri di accettazione

| Scenario | Risultato obbligatorio |
| --- | --- |
| Live lunga, molti chunk | Segue ultimo chunk senza tornare in cima |
| Utente risale il testo | Nuovi chunk non disturbano la lettura; Torna al live funziona |
| Live con più sorgenti | Sessioni e controlli isolati, progressi corretti |
| Buffer sotto pressione | Accumulo controllato, no perdite silenziose |
| Completa buffer | Residuo processato secondo semantica effettiva |
| Cambio di stato rapido | Stop/complete/rimozione robusti |
| Modifica di 50 interventi | Ogni edit mostrato come salvato si ritrova al riavvio |
| Chiusura improvvisa | Nessuna corruzione e recovery definito |
| Undo dopo autosave | Testo precedente ripristinato |
| 9 speaker | Tutti visibili tramite scorrimento e rinominabili |
| Overlap | Interventi e speaker concorrenti restano distinguibili |
| Player segue audio | Highlight/scroll corretto; non ruba focus durante edit |
| Click timestamp | Seek al punto originale corretto |
| Click riunione recente | Navigazione e focus visivo verso editor |
| Batch multi-file | Progresso del file e della coda attendibile |
| Riavvio programma | Titoli, speaker, correzioni, link file conservati |
| Esportazione | TXT/SRT corretti e VTT rimosso senza regressioni |
| Finestra piccola/desktop | Layout responsive, niente overflow e controlli raggiungibili |

### Prove trasversali

- **Prestazioni:** confrontare alimentazione/batteria e carico; misurare latenza, profondità coda, memoria, CPU/GPU, non dedurre la causa della lentezza dalla sola trascrizione.
- **Fedele UX:** screenshot prima/dopo in almeno 3 formati, incluso circa 1650x930; test scroll, hover, focus, tooltip, contrasto, tastiera.
- **Memoria Linux:** preferire PSS da /proc/<pid>/smaps_rollup a somme RSS.
- **Integrità:** migrazioni, rinomina, import/export, backup/recovery, file originari eliminati, diarizzazione ricalcolata, compatibilità con vecchie riunioni.
- **No false success:** documentare test mancanti e bug residui.

## 12. Questioni da verificare tecnicamente (non presupporre)

| Segnale nel feedback | Verifica necessaria |
| --- | --- |
| "Completa buffer" | Termina cattura e drena? o altra semantica? |
| "Ferma" | Stop immediato? cosa conserva o perde? |
| Buffer al 484% | Unità e denominatore? accumulo reale? |
| Coda 0 ms | Quale coda? è confrontabile con la misura del buffer? |
| Player forse a 16kHz | Quale media sorgente usa effettivamente? |
| Qwen + Community-1 | Modello, versioni, pipeline e configurazione nel repo |
| Advanced | Parametri realmente utilizzati e qualità misurabile |
| Autosave | Quando è garantita la durabilità? come gestire scritture fallite? |
| VTT | Dipendenze di export, storia, eventuali API/integrazioni |
| Power / GPU | Effetti reali sulla velocità e sulla coda |

## 13. Risultato finale atteso

- **Live:** testo protagonista, poche informazioni tecniche, scroll corretto, stabilità sotto carico.
- **File:** tre aree semplici con avanzamento integrato in coda.
- **Riunioni:** archivio denso e navigazione diretta, audio originale, correzioni automatiche, sincronizzazione audio-testo e editor ridisegnato.
- **Cronologia:** titoli comprensibili, personalizzabili, recovery preservato.
- **Impostazioni:** modelli e opzioni ridotti **dopo** verifica dell'accuratezza.
- **Log:** funzionalità attuali mantenute.

**Ordine di valore:** prima proteggere le modifiche e diagnosticare il buffer, poi ridisegnare l'interfaccia senza alterare la logica corretta.

## 14. Istruzioni operative per un altro agente

1. Leggere questa roadmap per intero e il README/ROADMAP preesistenti; usare la trascrizione e gli screenshot originali quando disponibili. **Non trattare le descrizioni come audit del codice già effettuato.**
2. Fare audit e test baseline **prima** di modificare. Inventariare state ownership, persistenza, threading e integrazione nativa.
3. Lavorare per fasi e per ID; prioritizzare P0 e preservare comportamenti noti.
4. Per ogni modifica: identificare ownership, progettare API, error handling, concorrenza e persistenza; implementare il backend prima del collegamento QML e dei test.
5. Prima di finalizzare una UI di revisione presentare le **dieci varianti** all'utente; le descrizioni A1–B5 sono specifiche approvate, non design già scelto.
6. Non eliminare Avanzate finché l'audit di qualità non ne giustifica la rimozione; non eliminare file/audio/modelli dell'utente durante la migrazione.
7. Eseguire verifiche misurabili e riportare **che cosa è cambiato, cosa è stato testato e che cosa resta non verificato**.
8. Non dichiarare completato alcun item sulla sola base di questo documento: i suoi requisiti sono **approvati, non implementati**.

### Fonte primaria e riferimenti

- Trascrizione dell'utilizzo Live del 29 ottobre 2026, 271 righe, fornita nella conversazione; screenshot "UI Live.png", "UI File.png", "UI Riunione 1.png", "UI Riunione 2.png".
- Sezione Live e File: trascrizione circa righe 15–103; Riunione e revisione: circa 105–203; Cronologia/Impostazioni/Log e scroll bug: circa 204–271.
- Documentazione ufficiale Qt Quick ListView: https://doc.qt.io/qt-6/qml-qtquick-listview.html
- Documentazione ufficiale Qt Multimedia MediaPlayer: https://doc.qt.io/qt-6/qml-qtmultimedia-mediaplayer.html
- Documentazione ufficiale Qt Quick ScrollBar: https://doc.qt.io/qt-6/qml-qtquick-controls-scrollbar.html

_Nessuna modifica di codice o prova di esecuzione è attestata da questa roadmap. La sua pubblicazione serve a trasferire i requisiti approvati a un agente di sviluppo._
