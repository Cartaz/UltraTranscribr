# PyTorch XPU inference

UltraTranscribr usa `core/torch_xpu.py` come unico proprietario del device PyTorch Intel XPU.

## Componenti

- Whisper continua a usare `whisper.cpp` compilato con GGML SYCL.
- Riunione usa pyannote Community-1 sul device restituito dal runtime XPU.
- Modalità Musica usa `demucs-infer`/HTDemucs sullo stesso device XPU.

Il runtime valida `torch.xpu.is_available()`, il numero di device e una reale operazione tensoriale prima di dichiarare la GPU disponibile.

## Policy

Non sono previsti fallback automatici a CPU o a backend di inferenza alternativi. Se XPU o un operatore necessario non sono disponibili, l'operazione richiesta fallisce con un errore esplicito.

Questa scelta mantiene un solo comportamento operativo supportato e rende diagnostici gli errori di installazione invece di nasconderli dietro risultati prodotti da una pipeline diversa.

## Validazione fisica

La CI headless può verificare contratti, lifecycle e device ownership tramite mock, ma non certifica il supporto degli operatori sulla GPU dell'utente. Dopo `./install.sh`, `python -m core.environment_check` esegue il probe XPU reale. La prima esecuzione di Community-1 e HTDemucs sul sistema target costituisce anche il controllo degli operatori specifici dei due modelli.
