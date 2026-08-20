# core/transcriber.py
"""Thread consumer per la trascrizione audio live con whisper-server SYCL.

Carica il modello Whisper e trascrive continuamente i blocchi audio
dal BufferManager tramite il backend whisper-server (API REST).
Esegue in un thread dedicato e comunica con l'interfaccia tramite
l'event bus.

A differenza della versione faster-whisper, questo modulo invia i
segmenti audio al server whisper.cpp via HTTP, senza caricare il
modello direttamente in Python. Il modello e caricato dal server
SYCL all'avvio del backend.

Include rilevamento del silenzio lato client: i segmenti con RMS
sotto la soglia vengono saltati per prevenire allucinazioni del
modello ("grazie a tutti", "thank you", ecc.) durante il silenzio.

Key behaviours:
  - Concatenazione di blocchi in segmenti con overlap
  - condition_on_previous_text via prompt (contesto inter-chunk)
  - Deduplicazione anti-allucinazione delegata a text_dedup.py
  - Rilevamento silenzio lato client con RMS finestrato (skip segmenti muti)
  - Rimozione overlap basata su timestamps (verbose_json) con filtro diretto
    per timestamp dei segmenti (come alltranscribr), non ricerca anchor
  - NO flush su buffer vuoto durante cattura attiva (evita segmenti corti)
  - Strippare l'overlap solo quando c'e overlap_buffer reale dal segmento
    precedente (nel flush finale senza overlap, skip_first_s = 0)
  - Auto-stop quando buffer vuoto e input_closed (drain mode)
  - Conversione audio numpy in WAV per la REST API

Classes:
    TranscriberThread: Thread consumer per trascrizione live.
"""

from __future__ import annotations

import logging
import struct
import threading
from queue import Empty

import numpy as np

from config.constants import ProcessDefaults
from config.settings import Settings
from core.buffer_manager import BufferManager
from core.event_bus import EventBus
from core.models import StatusEnum
from core.text_dedup import deduplicate_text
from core.whisper_backend import WhisperBackend

logger = logging.getLogger(__name__)


class TranscriberThread(threading.Thread):
    """Thread consumer che trascrive audio dal buffer usando whisper-server.

    Usa sovrapposizione scorrevole (sliding-window overlap) per evitare
    il taglio di parole ai confini dei segmenti. L'audio viene convertito
    in WAV e inviato al server tramite l'API REST OpenAI-compatible.

    I segmenti silenziosi (RMS sotto la soglia) vengono saltati per
    prevenire allucinazioni del modello durante il silenzio. Il VAD
    lato server (flag --vad) fornisce un ulteriore livello di filtro.

    FLUSH SOLO A SEGMENTO PIENO (NO FLUSH SU BUFFER VUOTO):
        Durante la cattura attiva (input_closed=False), il transcriber
        NON fa MAI flush quando il buffer si svuota (timeout Empty).
        Il buffer vuoto significa solo che la GPU ha consumato i chunk
        piu velocemente di quanto la cattura li producesse, NON che
        l'audio e finito. Flushing su buffer vuoto creava segmenti
        corti (5-7s) con alto rapporto overlap/audio (~30-40%),
        causando perdita di parole ai boundary tra segmenti.

        Ora il flush avviene SOLO quando:
          1. Il segmento raggiunge _segment_samples (10s) — flush normale
          2. La cattura viene fermata (input_closed) — drain finale
          3. Lo stop_event viene attivato — arresto forzato

        L'utente usa il pulsante "fine audio" per terminare la
        sessione, che attiva input_closed e scatena il drain di tutti
        i segmenti residui, inclusi quelli parziali.

    OVERLAP REMOVAL STRATEGY:
        La rimozione dell'overlap usa un approccio a cascata:
          1. Con word timestamps: filtro diretto per timestamp
             (come alltranscribr), saltando le word il cui end e <=
             skip_first_s. Questo e il metodo piu preciso e affidabile.
          2. Con solo segment timestamps: ricostruzione dai segmenti
             il cui end > skip_first_s.
          3. Senza timestamps: confronto col testo precedente e
             stima temporale con margine di sicurezza.

    Args:
        buffer: BufferManager da cui prelevare i blocchi audio.
        backend: WhisperBackend per la comunicazione col server.
        settings: Impostazioni dell'applicazione.
    """

    def __init__(
        self,
        buffer: BufferManager,
        backend: WhisperBackend,
        settings: Settings,
    ) -> None:
        super().__init__(daemon=True, name="TranscriberThread")
        self._buffer = buffer
        self._backend = backend
        self._settings = settings
        self._stop_event = threading.Event()
        self._current_segment: list[np.ndarray] = []
        self._segment_sample_count = 0
        self._segment_samples = int(settings.sample_rate * 10.0)
        self._min_segment_samples = int(settings.sample_rate * 2.0)
        self._overlap_samples = int(settings.sample_rate * 2.0)
        self._overlap_buffer: np.ndarray = np.array([], dtype=np.float32)
        self._silence_threshold = ProcessDefaults.SILENCE_RMS_THRESHOLD
        # Traccia l'ultimo testo emesso per deduplicare l'overlap
        # tra segmenti consecutivi. Contiene le ultime parole del
        # segmento precedente, per rimuoverle se compaiono anche
        # all'inizio del segmento corrente (zona di overlap).
        self._last_emitted_text: str = ""

    def run(self) -> None:
        """Loop principale: preleva blocchi, accumula e trascrive."""
        bus = EventBus()
        bus.emit("transcriber_status_changed", StatusEnum.RUNNING.value)
        logger.info("TranscriberThread avviato -- backend SYCL")

        try:
            self._transcription_loop()
        except Exception as exc:
            if not self._stop_event.is_set():
                logger.error("Errore trascrizione: %s", exc)
                bus.emit("transcriber_error", f"Errore trascrizione: {exc}")
                bus.emit("transcriber_status_changed", StatusEnum.ERROR.value)
        finally:
            self._flush_segment(is_final=True)
            bus.emit("transcriber_status_changed", StatusEnum.STOPPED.value)
            logger.info("TranscriberThread fermato")

    def stop(self) -> None:
        """Segnala al transcriber di fermarsi."""
        self._stop_event.set()

    def _transcription_loop(self) -> None:
        """Prelieva blocchi dal buffer, accumula e trascrive.

        Quando il buffer e vuoto e input_closed e True (drain mode),
        il transcriber svuota il segmento corrente e si ferma autonomamente.

        NO FLUSH SU BUFFER VUOTO DURANTE CATTURA ATTIVA:
            Durante la cattura attiva (input_closed=False), il buffer
            vuoto (timeout Empty) NON e un segnale che l'audio e finito
            — significa solo che la GPU ha consumato i chunk piu
            velocemente di quanto la cattura li producesse. Flushing
            su buffer vuoto creava segmenti corti (5-7s) con alto
            rapporto overlap/audio, causando perdita di parole.

            Il flush avviene SOLO quando il segmento raggiunge
            _segment_samples (10s target). Quando l'utente preme
            "fine audio", input_closed diventa True e il drain
            finale emette tutti i segmenti residui.

            Il timeout di get() e 1.0s per un rilevamento rapido
            di input_closed (drain mode) dopo che l'utente preme
            "fine audio".
        """
        bus = EventBus()
        while not self._stop_event.is_set():
            try:
                # Timeout 1.0s: sufficiente per rilevare rapidamente
                # input_closed (drain mode) quando l'utente preme
                # "fine audio". Non influisce sulla logica di flush
                # perche non si flushea piu su buffer vuoto.
                chunk = self._buffer.get(timeout=1.0)
            except Empty:
                # Durante la cattura attiva, il buffer vuoto e normale:
                # la GPU ha semplicemente consumato i chunk piu velocemente
                # della cattura. NON flusheare il segmento: aspetta che
                # arrivi altro audio o che la cattura venga fermata.
                # Il flush su buffer vuoto era la causa della perdita di
                # parole con GPU veloce, perche creava segmenti corti
                # con alto rapporto overlap/audio.
                if self._buffer.input_closed and self._buffer.is_empty:
                    logger.info("Drain completato -- buffer vuoto e input chiuso")
                    bus.emit("transcriber_drained", None)
                    break

                bus.emit("transcriber_buffer_level", self._buffer.buffer_level)
                continue
            except Exception as exc:
                logger.warning("Errore prelievo dal buffer: %s", exc)
                bus.emit("transcriber_buffer_level", self._buffer.buffer_level)
                continue

            self._current_segment.append(chunk)
            self._segment_sample_count += chunk.shape[0]
            bus.emit("transcriber_buffer_level", self._buffer.buffer_level)

            # L'UNICO trigger di flush durante la cattura attiva:
            # il segmento ha raggiunto la dimensione target (10s).
            # Questo garantisce segmenti di dimensione costante con
            # rapporto overlap/audio stabile (~20%), eliminando la
            # perdita di parole causata da segmenti corti.
            if self._segment_sample_count >= self._segment_samples:
                self._flush_segment(is_final=False)

        # Flush finale: emette il segmento residuo (anche parziale)
        # quando il loop termina per stop_event o drain completato.
        # is_final=True preserva il contesto per un'eventuale ripresa.
        self._flush_segment(is_final=True)

    def _flush_segment(self, is_final: bool = False) -> None:
        """Costruisce il segmento audio con overlap e trascrive.

        Args:
            is_final: Se True, e l'ultimo flush (non salvare overlap per il
                segmento successivo).
        """
        if not self._current_segment:
            return
        if self._segment_sample_count < self._min_segment_samples and not is_final:
            return

        parts: list[np.ndarray] = []
        overlap_s = 0.0
        if self._overlap_buffer.size > 0:
            parts.append(self._overlap_buffer)
            overlap_s = self._overlap_buffer.size / self._settings.sample_rate
        parts.extend(self._current_segment)
        audio = np.concatenate(parts, axis=0)

        self._overlap_buffer = np.array([], dtype=np.float32)
        if (not is_final and self._overlap_samples > 0
                and audio.shape[0] > self._overlap_samples * 2):
            self._overlap_buffer = audio[-self._overlap_samples:].copy()

        self._current_segment = []
        self._segment_sample_count = 0

        # L'overlap va strippato SOLO se c'e effettivamente overlap_buffer
        # dal segmento precedente (overlap_s > 0). Se non c'e overlap
        # (primo segmento, oppure is_final senza overlap precedente),
        # skip_first_s = 0 e tutto il testo viene preservato.
        #
        # Prima la logica era: skip = overlap_s (SEMPRE), che causava
        # perdita di contenuto nel flush finale quando il segmento
        # precedente non aveva overlap ma il codice rimuoveva comunque
        # i primi overlap_s secondi di testo.
        #
        # alltranscribr usa: skip = 0.0 if is_final else overlap_s
        # che sul flush finale non rimuove nulla. Tuttavia questo
        # causava duplicazione quando c'era overlap reale. La soluzione
        # corretta e: skip = overlap_s se c'e overlap reale (overlap_s > 0),
        # altrimenti 0.0.
        skip = overlap_s if overlap_s > 0.0 else 0.0
        self._transcribe_audio(audio, skip_first_s=skip)

    def _transcribe_audio(self, audio: np.ndarray, skip_first_s: float = 0.0) -> None:
        """Invia audio al server whisper e emette i risultati.

        Prima di inviare, verifica che il segmento non sia silenzioso
        tramite il calcolo RMS finestrato. I segmenti completamente
        muti vengono saltati per prevenire allucinazioni del modello
        ("grazie a tutti", ecc.).

        Il parametro skip_first_s indica quanti secondi iniziali
        dell'audio corrispondono all'overlap col segmento precedente.
        L'audio completo (incluso l'overlap) viene inviato a Whisper
        per garantire contesto, ma il testo corrispondente all'overlap
        viene rimosso dal risultato prima dell'emissione.

        Il testo del segmento precedente (_last_emitted_text) viene
        passato come prompt al server Whisper. Questo implementa
        condition_on_previous_text lato client e permette al modello
        di usare il contesto del segmento precedente per una decodifica
        piu accurata, specialmente al boundary tra chunk dove le parole
        possono essere tagliate a meta.

        Args:
            audio: Array numpy float32 a 16kHz.
            skip_first_s: Secondi iniziali da saltare (overlap).
        """
        # Rilevamento silenzio lato client con RMS finestrato.
        # Previene allucinazioni senza scartare segmenti che contengono
        # speech quieto circondato da silenzio.
        if self._is_silent(audio):
            logger.debug(
                "Segmento silenzioso (RMS %.4f < soglia %.4f), trascrizione saltata",
                self._compute_rms(audio), self._silence_threshold,
            )
            return

        try:
            wav_bytes = self._numpy_to_wav(audio)
            # Passa il testo del segmento precedente come prompt a Whisper.
            # Questo implementa condition_on_previous_text lato client:
            # il modello usa il contesto del chunk precedente per decodificare
            # piu accuratamente le parole all'inizio del segmento corrente,
            # riducendo drasticamente la perdita di parole al boundary.
            # Si usano solo gli ultimi 500 caratteri per rimanere nel
            # contesto di decodifica senza sovraccaricare il prompt.
            context_prompt = self._last_emitted_text[-500:] if self._last_emitted_text else None

            # Richiede verbose_json per ottenere word-level timestamps,
            # che permettono una rimozione precisa dell'overlap basata
            # sui timestamp anziche su stime approssimative.
            result = self._backend.transcribe_audio(
                audio_data=wav_bytes,
                language=self._settings.language,
                prompt=context_prompt,
                verbose=True,
            )

            # Gestisce sia il caso verbose (dict) che non-verbose (str)
            if isinstance(result, dict):
                text = result.get("text", "")
                segments = result.get("segments", [])
            else:
                text = result
                segments = []

            if text.strip():
                # Log diagnostico: traccia il testo prima e dopo la
                # rimozione dell'overlap per verificare che non ci
                # sia perdita di contenuto
                raw_len = len(text.strip().split())

                # Ordine corretto: prima rimuovere l'overlap, poi
                # deduplicare. L'ordine precedente (dedup prima di
                # strip_overlap) causava un bug perche _strip_overlap_by_timestamps
                # ricostruisce il testo dai segmenti originali (pre-dedup),
                # rendendo la dedup precedente inutile. Inoltre, la
                # dedup potrebbe rimuovere parole legittime che sembrano
                # ripetizioni ma sono nella zona di overlap.
                cleaned = text.strip()
                # Rimuovi il testo della zona di overlap (skip_first_s)
                # che e gia stato emesso nel segmento precedente.
                if skip_first_s > 0.0:
                    if segments:
                        # Con word timestamps: rimozione precisa basata
                        # sui timestamp dei segmenti restituiti dal server
                        cleaned = self._strip_overlap_by_timestamps(
                            cleaned, skip_first_s, segments, audio.shape[0]
                        )
                    else:
                        # Senza timestamps: fallback alla strategia ibrida
                        cleaned = self._strip_overlap_text(
                            cleaned, skip_first_s, audio.shape[0]
                        )
                # Deduplica DOPO la rimozione dell'overlap per evitare
                # che la dedup interferisca con il confronto testuale
                # dell'overlap e per pulire ripetizioni residue.
                cleaned = deduplicate_text(cleaned)

                # Log diagnostico: se la rimozione dell'overlap ha
                # rimosso piu del 70% delle parole, qualcosa potrebbe
                # non funzionare correttamente
                cleaned_len = len(cleaned.split()) if cleaned.strip() else 0
                if skip_first_s > 0.0 and raw_len > 5 and cleaned_len < raw_len * 0.3:
                    logger.warning(
                        "Rimozione overlap aggressiva: %d parole -> %d parole "
                        "(skip_first_s=%.1fs). Possibile perdita di contenuto. "
                        "Testo originale: '%s', Testo pulito: '%s'",
                        raw_len, cleaned_len, skip_first_s,
                        text.strip()[:200], cleaned[:200],
                    )

                if cleaned.strip():
                    self._last_emitted_text = cleaned.strip()
                    EventBus().emit("transcriber_new_text", cleaned.strip())
        except RuntimeError as exc:
            logger.error("Trascrizione segmento fallita: %s", exc)
            EventBus().emit("transcriber_error", f"Errore segmento: {exc}")

    def _strip_overlap_by_timestamps(
        self, text: str, skip_first_s: float, segments: list[dict],
        total_samples: int,
    ) -> str:
        """Rimuove il testo corrispondente alla zona di overlap usando i timestamps.

        Quando whisper-server restituisce segmenti con timestamps
        (response_format=verbose_json), questa funzione identifica
        la porzione di testo che cade nella zona di overlap (i primi
        skip_first_s secondi) e la rimuove.

        ATTENZIONE: I word timestamps di whisper.cpp restituiscono
        token a livello di sillaba/sub-word (es. "arch", "itet", "to"
        invece di "architetto"), NON parole complete come fa
        faster-whisper (alltranscribr). Per questo motivo, NON si
        ricostruisce MAI il testo dai word tokens — si usano solo
        per determinare il punto di taglio temporale. Il testo viene
        sempre preso dal campo "text" dei segmenti.

        Strategia (in ordine di priorita):
          1. Segment-level filtering: mantiene i segmenti il cui
             end > skip_first_s e usa il loro campo "text" direttamente.
             I segmenti che attraversano il boundary (start < skip_first_s
             ma end > skip_first_s) vengono inclusi per intero per non
             tagliare parole a meta. Eventuale overlap residuo viene
             gestito dalla dedup successiva.
          2. Fallback: ritorna il testo originale e affida la pulizia
             alla dedup successiva.

        Args:
            text: Testo trascritto completo del segmento.
            skip_first_s: Secondi iniziali di overlap da saltare.
            segments: Lista di segmenti con timestamps dal server,
                ciascuno con chiavi "start", "end", "text".
            total_samples: Numero totale di campioni dell'audio.

        Returns:
            Testo con la porzione di overlap rimossa.
        """
        if not segments or skip_first_s <= 0.0:
            return text

        # Segment-level filtering: usa i segment timestamps per
        # determinare quali segmenti cadono nella zona di overlap
        # e quali no. Il testo viene SEMPRE preso dal campo "text"
        # dei segmenti, MAI dai word tokens, perche whisper.cpp
        # restituisce sillabe/sub-word invece di parole complete.
        # Esempio: word tokens di "architetto" = ["arch", "itet", "to"]
        # che concatenati con spazi diventano "arch itet to".
        kept_parts: list[str] = []
        kept_count = 0
        skipped_count = 0

        for seg in segments:
            seg_start = seg.get("start", 0.0)
            seg_end = seg.get("end", 0.0)
            seg_text = seg.get("text", "").strip()

            # Salta segmenti completamente nella zona di overlap
            if seg_end <= skip_first_s:
                skipped_count += 1
                continue

            # Il segmento inizia dopo l'overlap oppure attraversa
            # il boundary (start < skip_first_s ma end > skip_first_s).
            # In entrambi i casi, includiamo il segmento per intero
            # per non tagliare parole a meta. L'eventuale piccolo
            # overlap residuo nel segmento che attraversa il boundary
            # viene gestito dalla dedup successiva.
            if seg_text:
                kept_parts.append(seg_text)
            kept_count += 1

        if kept_parts:
            result = " ".join(kept_parts)
            logger.debug(
                "Overlap rimosso via segment timestamps: %d saltati, "
                "%d mantenuti (skip_first_s=%.1fs)",
                skipped_count, kept_count, skip_first_s,
            )
            return result

        # Fallback: ritorna il testo originale
        # La dedup successiva gestira eventuali duplicati.
        # Meglio avere una piccola duplicazione che perdere contenuto.
        logger.warning(
            "Impossibile rimuovere overlap via timestamps (nessun segmento "
            "dopo skip_first_s=%.1fs), affido alla dedup. Testo: '%s'",
            skip_first_s, text[:100],
        )
        return text

    def _strip_overlap_text(
        self, text: str, skip_first_s: float, total_samples: int,
    ) -> str:
        """Rimuove il testo corrispondente alla zona di overlap.

        Quando l'audio contiene un overlap dal segmento precedente
        (skip_first_s > 0), il testo di quella zona e gia stato
        emesso e deve essere rimosso per evitare duplicazioni.

        Questo metodo viene usato solo come fallback quando il server
        non restituisce timestamps (verbose_json non supportato o
        fallito). La rimozione basata su timestamps e sempre preferita.

        Strategia (in ordine di priorita):
          1. Confronto col testo del segmento precedente: se le parole
             iniziali del testo corrente corrispondono alla coda del
             testo precedente, le rimuove. Richiede match di almeno
             2 parole (non 1) per evitare false positivi.
          2. Stima basata sul rapporto temporale con MARGINE DI
             SICUREZZA: calcola la frazione di testo da saltare come
             skip_first_s / durata_totale e rimuove le parole iniziali
             corrispondenti, MA con un fattore di riduzione del 30%
             per evitare di saltare parole reali. E' preferibile
             avere una piccola duplicazione (gestita dalla dedup)
             piuttosto che perdere contenuto.

        Args:
            text: Testo trascritto.
            skip_first_s: Secondi iniziali di overlap da saltare.
            total_samples: Numero totale di campioni dell'audio.

        Returns:
            Testo con la porzione di overlap rimossa.
        """
        if not text.strip() or skip_first_s <= 0.0:
            return text

        words = text.split()
        if not words:
            return text

        # Strategia 1: confronto col testo precedente
        if self._last_emitted_text:
            prev_words = self._last_emitted_text.split()
            # Cerca la sequenza di parole precedenti che compare
            # all'inizio del testo corrente (overlap testuale).
            # Richiede almeno 2 parole di match per evitare false
            # positivi con articoli comuni ("the", "a", "il", "lo").
            best_match_len = 0
            max_check = min(len(prev_words), len(words), 20)
            for match_len in range(max_check, 1, -1):
                tail_prev = [w.lower().strip(".,;:!?") for w in prev_words[-match_len:]]
                head_curr = [w.lower().strip(".,;:!?") for w in words[:match_len]]
                if tail_prev == head_curr and match_len >= 2:
                    best_match_len = match_len
                    break
            if best_match_len > 0:
                logger.debug(
                    "Overlap testuale rimosso: %d parole (%s)",
                    best_match_len, " ".join(words[:best_match_len]),
                )
                return " ".join(words[best_match_len:])

        # Strategia 2: stima basata sul rapporto temporale
        # CON MARGINE DI SICUREZZA: riduce del 30% il numero di parole
        # da saltare per evitare di tagliare contenuto reale.
        # La dedup successiva gestira eventuali duplicati residui.
        sr = self._settings.sample_rate
        total_s = total_samples / sr if sr > 0 else 1.0
        if total_s <= 0.0:
            return text

        skip_ratio = skip_first_s / total_s
        # Margine di sicurezza del 30%: meglio lasciare qualche parola
        # duplicata (gestita dalla dedup) che tagliare parole reali.
        words_to_skip = int(len(words) * skip_ratio * 0.7 + 0.5)
        # Soglia di sicurezza: non saltare piu del 40% delle parole
        # (ridotto da 60% per evitare perdita di contenuto)
        words_to_skip = min(words_to_skip, int(len(words) * 0.4))
        if words_to_skip > 0 and words_to_skip < len(words):
            logger.debug(
                "Overlap temporale rimosso: %d/%d parole (%.1fs/%.1fs, "
                "ratio=%.2f, safety=0.7)",
                words_to_skip, len(words), skip_first_s, total_s,
                skip_ratio,
            )
            return " ".join(words[words_to_skip:])

        return text

    @staticmethod
    def _compute_rms(audio: np.ndarray) -> float:
        """Calcola il valore RMS (Root Mean Square) dell'audio.

        Args:
            audio: Array numpy float32.

        Returns:
            Valore RMS dell'audio.
        """
        if audio.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(audio ** 2)))

    def _is_silent(self, audio: np.ndarray) -> bool:
        """Verifica se l'audio e silenzioso usando RMS finestrato.

        Un segmento e considerato silenzioso solo se NESSUNA finestra
        di 1 secondo supera la soglia RMS. Questo previene lo scarto
        di segmenti che contengono speech quieto circondato da silenzio,
        che con il vecchio approccio (RMS globale) venivano erroneamente
        classificati come silenziosi.

        NOTA: La soglia e stata abbassata da 0.01 a 0.005 per evitare di
        scartare speech quieto. Whisper e molto bravo a trascrivere
        audio quieto, e meglio rischiare un'allucinazione occasionale
        (gestita da strip_hallucinations) che perdere contenuto reale.
        Questo e coerente con l'approccio di alltranscribr che non ha
        silence detection lato client e non perde contenuto.

        Args:
            audio: Array numpy float32.

        Returns:
            True se il segmento e silenzioso.
        """
        if audio.size == 0:
            return True

        # Se l'audio e piu corto di 1 secondo, usa RMS globale
        window_size = int(self._settings.sample_rate * 1.0)
        if audio.size <= window_size:
            return self._compute_rms(audio) < self._silence_threshold

        # Controlla ogni finestra di 1 secondo. Se ALMENO UNA finestra
        # contiene audio sopra la soglia, il segmento NON e silenzioso.
        for i in range(0, audio.size, window_size):
            window = audio[i:i + window_size]
            if self._compute_rms(window) >= self._silence_threshold:
                return False

        return True

    @staticmethod
    def _numpy_to_wav(audio: np.ndarray) -> bytes:
        """Converte un array numpy float32 in WAV 16-bit PCM.

        Genera un file WAV in memoria senza dipendenze esterne,
        usando struct per costruire l'header RIFF.

        Args:
            audio: Array numpy float32 mono a 16kHz.

        Returns:
            Bytes del file WAV.
        """
        sample_rate = 16000
        num_channels = 1
        sample_width = 2  # 16-bit

        # Normalizza e converte a int16
        audio_clipped = np.clip(audio, -1.0, 1.0)
        pcm_data = (audio_clipped * 32767).astype(np.int16)
        raw_bytes = pcm_data.tobytes()

        data_size = len(raw_bytes)
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + data_size,
            b"WAVE",
            b"fmt ",
            16,  # chunk size
            1,   # PCM format
            num_channels,
            sample_rate,
            sample_rate * num_channels * sample_width,
            num_channels * sample_width,
            sample_width * 8,
            b"data",
            data_size,
        )
        return header + raw_bytes
