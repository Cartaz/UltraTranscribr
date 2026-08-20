#!/usr/bin/env bash
# install.sh — Installazione UltraTranscribr con accelerazione SYCL su GPU Intel Arc
#
# Compila whisper.cpp con SYCL (Intel oneAPI / Level Zero), scarica il modello
# Whisper Large V3 Turbo, e configura il deploy self-contained nel virtualenv.
#
# L'isolamento vocale (Demucs + PyTorch CPU) e OPZIONALE e viene installato
# solo se richiesto. Non interferisce con l'accelerazione GPU SYCL.
#
# Requisiti: CachyOS/Arch Linux, Intel oneAPI Toolkit, driver Level Zero

# NOTA: usiamo set -uo pipefail (SENZA -e) per evitare che lo script muoia
# su comandi che ritornano non-zero. Gestiamo gli errori manualmente.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="UltraTranscribr"
APP_ID="com.ultratranscribr.app"
VENV_DIR="${SCRIPT_DIR}/.venv"
CACHE_DIR="${SCRIPT_DIR}/.cache"
WHISPER_CPP_DIR="${CACHE_DIR}/whisper.cpp"
DESKTOP_FILE="${HOME}/.local/share/applications/${APP_ID}.desktop"
ICON_SCALABLE_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"

# Sicurezza: non eseguire da dentro ~/.local/share/applications/
if [[ "${SCRIPT_DIR}" == "${HOME}/.local/share/applications"* ]]; then
    echo "ERRORE: non eseguire questo script da dentro ~/.local/share/applications/"
    exit 1
fi

echo "=== Installazione ${APP_NAME} con SYCL ==="

# ── Fase 1: Python ─────────────────────────────────────────────
echo ""
echo "[1/8] Ricerca Python 3.11+..."
PYTHON_CMD=""
for cmd in python3.12 python3.11 python3; do
    if command -v "${cmd}" &>/dev/null; then
        PY_VERSION=$("${cmd}" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        PY_MAJOR=$("${cmd}" -c "import sys; print(sys.version_info.major)")
        PY_MINOR=$("${cmd}" -c "import sys; print(sys.version_info.minor)")
        if [[ "${PY_MAJOR}" -ge 3 && "${PY_MINOR}" -ge 11 ]]; then
            PYTHON_CMD="${cmd}"
            echo "  Trovato: ${cmd} (${PY_VERSION})"
            break
        fi
    fi
done

if [[ -z "${PYTHON_CMD}" ]]; then
    echo "ERRORE: Python 3.11+ non trovato. Installare con: sudo pacman -S python"
    exit 1
fi

# ── Fase 2: Virtual Environment ────────────────────────────────
echo ""
echo "[2/8] Creazione virtualenv..."

# Backup del binary whisper-server esistente se presente
WHISPER_SERVER_BACKUP=""
if [[ -f "${VENV_DIR}/bin/whisper-server" ]]; then
    WHISPER_SERVER_BACKUP="${VENV_DIR}/bin/whisper-server.bak"
    echo "  Backup whisper-server esistente..."
    cp "${VENV_DIR}/bin/whisper-server" "${WHISPER_SERVER_BACKUP}"
fi

if [[ ! -d "${VENV_DIR}" ]]; then
    "${PYTHON_CMD}" -m venv "${VENV_DIR}"
fi

echo "  Aggiornamento pip..."
"${VENV_DIR}/bin/pip" install --upgrade pip

# ── Fase 3: Dipendenze Python (core, senza PyTorch) ───────────
echo ""
echo "[3/8] Installazione dipendenze Python..."
"${VENV_DIR}/bin/pip" install -r "${SCRIPT_DIR}/requirements.txt"

# ── Fase 4: Isolamento vocale OPZIONALE (Demucs + PyTorch CPU) ─
echo ""
echo "[4/8] Isolamento vocale (opzionale, solo per musica)..."
echo "  Demucs usa PyTorch su CPU — non interferisce con la GPU SYCL."
echo "  Serve solo se si vuole isolare la voce da brani musicali."

read -r -p "  Installare Demucs + PyTorch CPU? (~200 MB) [s/N]: " INSTALL_DEMUCS
if [[ "${INSTALL_DEMUCS}" =~ ^[sSyY]$ ]]; then
    echo "  Installazione PyTorch CPU-only..."
    "${VENV_DIR}/bin/pip" install \
        --index-url https://download.pytorch.org/whl/cpu \
        torch torchaudio || echo "  Avviso: PyTorch non installato"
    "${VENV_DIR}/bin/pip" install demucs || echo "  Avviso: Demucs non installato"
    echo "  Demucs installato."
else
    echo "  Demucs saltato. Per installarlo in seguito:"
    echo "    .venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio"
    echo "    .venv/bin/pip install demucs"
fi

# ── Fase 5: Compilazione whisper.cpp con SYCL ──────────────────
echo ""
echo "[5/8] Compilazione whisper.cpp con SYCL..."

# Verifica Intel oneAPI
ONEAPI_ROOT="/opt/intel/oneapi"
if [[ ! -f "${ONEAPI_ROOT}/setvars.sh" ]]; then
    echo "ERRORE: Intel oneAPI Toolkit non trovato."
    echo "  Installare con: sudo pacman -S intel-oneapi-basekit"
    echo "  Poi eseguire: source /opt/intel/oneapi/setvars.sh"
    exit 1
fi

# ── Source oneAPI environment ──
# CRITICO: setvars.sh e NECESSARIO per impostare ONEAPI_ROOT, MKL_DIR,
# CMAKE_PREFIX_PATH e tutte le variabili richieste dalla compilazione SYCL.
# Disabilitiamo temporaneamente set -u (nounset) perché setvars.sh
# referenzia variabili non definite, e set -e e già disabilitato.
echo "  Configurazione ambiente Intel oneAPI (source setvars.sh)..."
set +u
source "${ONEAPI_ROOT}/setvars.sh" 2>/dev/null || true
set -u

# Verifica che i compilatori siano ora disponibili
if ! command -v icx &>/dev/null || ! command -v icpx &>/dev/null; then
    echo "ERRORE: Compilatori Intel (icx/icpx) non trovati dopo il source di oneAPI."
    echo "  Verificare che intel-oneapi-basekit sia installato correttamente."
    exit 1
fi

echo "  Compilatori: icx=$(command -v icx), icpx=$(command -v icpx)"
echo "  ONEAPI_ROOT=${ONEAPI_ROOT:-non impostato}"

# Verifica MKL (richiesto per la compilazione SYCL)
if [[ -n "${MKL_DIR:-}" ]] || [[ -d "${ONEAPI_ROOT}/mkl" ]]; then
    echo "  MKL: trovato (${MKL_DIR:-${ONEAPI_ROOT}/mkl})"
else
    echo "  ATTENZIONE: MKL non trovato. Potrebbe essere necessario installare:"
    echo "    sudo pacman -S intel-oneapi-mkl"
    echo "  Provero la compilazione senza MKL..."
fi

# Clone whisper.cpp se non presente
if [[ ! -d "${WHISPER_CPP_DIR}" ]]; then
    echo "  Clone whisper.cpp da GitHub..."
    mkdir -p "${CACHE_DIR}"
    git clone https://github.com/ggml-org/whisper.cpp.git "${WHISPER_CPP_DIR}" --depth 1
else
    echo "  whisper.cpp gia presente in cache, aggiorno..."
    cd "${WHISPER_CPP_DIR}" && git pull --ff-only 2>/dev/null || echo "  (aggiornamento saltato)"
fi

# Compilazione con CMake + SYCL
BUILD_DIR="${WHISPER_CPP_DIR}/build"
echo "  Compilazione con SYCL (questo puo richiedere alcuni minuti)..."
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

# CMake configuration
# -DGGML_SYCL=1 abilita il backend SYCL
# -DCMAKE_C_COMPILER=icx / -DCMAKE_CXX_COMPILER=icpx usano i compilatori Intel
# ONEAPI_ROOT e già impostato da setvars.sh, quindi cmake trovera MKL
cmake .. \
    -DGGML_SYCL=1 \
    -DCMAKE_C_COMPILER=icx \
    -DCMAKE_CXX_COMPILER=icpx \
    -DCMAKE_BUILD_TYPE=Release \
    2>&1 || {
        echo ""
        echo "ERRORE: CMake configuration fallita."
        echo ""
        echo "  Cause possibili:"
        echo "  1. MKL non installato: sudo pacman -S intel-oneapi-mkl"
        echo "  2. oneAPI non sourcato: source /opt/intel/oneapi/setvars.sh"
        echo "  3. Dipendenze mancanti: sudo pacman -S cmake level-zero-headers"
        echo ""
        echo "  Prova manualmente:"
        echo "    source /opt/intel/oneapi/setvars.sh"
        echo "    cd ${WHISPER_CPP_DIR} && mkdir -p build && cd build"
        echo "    cmake .. -DGGML_SYCL=1 -DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx"
        exit 1
    }

# Build
cmake --build . --config Release -j"$(nproc)" \
    2>&1 || {
        echo ""
        echo "ERRORE: Compilazione whisper.cpp fallita."
        echo "  Verificare i log sopra per dettagli."
        exit 1
    }

# Deploy del binary nel venv (immune da pacman)
echo "  Deploy whisper-server nel venv..."
SERVER_DEPLOYED=false

# Cerca il binary del server con tutti i nomi possibili
for candidate in \
    "${BUILD_DIR}/bin/whisper-server" \
    "${BUILD_DIR}/bin/server" \
    "${BUILD_DIR}/whisper-server" \
    "${BUILD_DIR}/server"; do
    if [[ -f "${candidate}" ]] && [[ -x "${candidate}" ]]; then
        cp "${candidate}" "${VENV_DIR}/bin/whisper-server"
        chmod +x "${VENV_DIR}/bin/whisper-server"
        echo "  whisper-server copiato da ${candidate}"
        SERVER_DEPLOYED=true
        break
    fi
done

# Se non trovato nei percorsi standard, cerca ricorsivamente
if [[ "${SERVER_DEPLOYED}" == false ]]; then
    SERVER_BIN=$(find "${BUILD_DIR}" -type f -name "whisper-server" -o -name "server" 2>/dev/null | head -1)
    if [[ -n "${SERVER_BIN}" ]]; then
        cp "${SERVER_BIN}" "${VENV_DIR}/bin/whisper-server"
        chmod +x "${VENV_DIR}/bin/whisper-server"
        echo "  whisper-server copiato da ${SERVER_BIN}"
        SERVER_DEPLOYED=true
    fi
fi

if [[ "${SERVER_DEPLOYED}" == false ]]; then
    echo "ERRORE: whisper-server non trovato nella build."
    echo "  Contenuto della directory di build:"
    find "${BUILD_DIR}" -type f -executable 2>/dev/null | head -20
    exit 1
fi

# Deploy delle librerie condivise nel venv
# Cerca ricorsivamente in tutta la build tree — CMake piazza le .so
# in sottodirectory (ggml/src/, src/, ggml/src/ggml-sycl/, ecc.)
echo "  Copia librerie condivise SYCL in ${VENV_DIR}/lib/..."
mkdir -p "${VENV_DIR}/lib"
while IFS= read -r -d '' lib; do
    cp -L "${lib}" "${VENV_DIR}/lib/"
    echo "    $(basename "${lib}")"
done < <(find "${BUILD_DIR}" -name 'lib*.so*' -type f -print0 2>/dev/null)
# Copia anche i symlink (libX.so -> libX.so.1 -> libX.so.1.0.0)
while IFS= read -r -d '' link; do
    dest_name="$(basename "${link}")"
    if [[ ! -e "${VENV_DIR}/lib/${dest_name}" ]]; then
        cp -L "${link}" "${VENV_DIR}/lib/${dest_name}" 2>/dev/null || true
    fi
done < <(find "${BUILD_DIR}" -name 'lib*.so*' -type l -print0 2>/dev/null)

# Copia librerie runtime oneAPI necessarie per SYCL
# Queste servono al processo whisper-server a runtime (senza source setvars.sh)
echo "  Copia librerie runtime Intel oneAPI..."
ONEAPI_LIBS_COPIED=0
for oneapi_dir in \
    "${ONEAPI_ROOT}/compiler/${ONEAPI_COMPILER_VER:-latest}/lib" \
    "${ONEAPI_ROOT}/tbb/${ONEAPI_TBB_VER:-latest}/lib/intel64/gcc4.8" \
    "${ONEAPI_ROOT}/mkl/${ONEAPI_MKL_VER:-latest}/lib" \
    "${ONEAPI_ROOT}/dnnl/${ONEAPI_DNNL_VER:-latest}/lib"; do
    if [[ -d "${oneapi_dir}" ]]; then
        for lib in "${oneapi_dir}"/lib*.so*; do
            if [[ -f "${lib}" ]]; then
                cp -L "${lib}" "${VENV_DIR}/lib/" 2>/dev/null || true
                ONEAPI_LIBS_COPIED=$((ONEAPI_LIBS_COPIED + 1))
            fi
        done
    fi
done
# Cerca nelle sottodirectory versionate se i link sopra non hanno funzionato
if [[ ${ONEAPI_LIBS_COPIED} -eq 0 ]]; then
    echo "  (ricerca automatica librerie oneAPI...)"
    for oneapi_dir in "${ONEAPI_ROOT}"/compiler/*/lib "${ONEAPI_ROOT}"/tbb/*/lib/intel64/gcc4.8 "${ONEAPI_ROOT}"/mkl/*/lib; do
        if [[ -d "${oneapi_dir}" ]]; then
            for lib in "${oneapi_dir}"/lib*.so*; do
                if [[ -f "${lib}" ]]; then
                    cp -L "${lib}" "${VENV_DIR}/lib/" 2>/dev/null || true
                    ONEAPI_LIBS_COPIED=$((ONEAPI_LIBS_COPIED + 1))
                fi
            done
        fi
    done
fi
echo "  Librerie oneAPI copiate: ${ONEAPI_LIBS_COPIED}"

# Verifica che il binary funzioni
echo "  Verifica binary SYCL..."
export LD_LIBRARY_PATH="${VENV_DIR}/lib:${LD_LIBRARY_PATH:-}"
if "${VENV_DIR}/bin/whisper-server" --help 2>&1 | head -3 | grep -qi "usage\|whisper"; then
    echo "  whisper-server: OK"
else
    echo "  ATTENZIONE: whisper-server potrebbe non funzionare correttamente"
    echo "  Output di --help:"
    "${VENV_DIR}/bin/whisper-server" --help 2>&1 | head -5
    echo ""
    echo "  Librerie in .venv/lib/:"
    ls -la "${VENV_DIR}/lib/"lib*.so* 2>/dev/null | head -20
    echo ""
    echo "  Dipendenze mancanti (ldd):"
    LD_LIBRARY_PATH="${VENV_DIR}/lib" ldd "${VENV_DIR}/bin/whisper-server" 2>&1 | grep "not found" || echo "  (nessuna)"
fi

# Pulizia build per recuperare spazio (~1 GB)
echo "  Pulizia directory di build..."
rm -rf "${BUILD_DIR}"

# ── Fase 6: Download modello da HuggingFace ────────────────────
echo ""
echo "[6/8] Download modello Whisper Large V3 Turbo da HuggingFace..."
MODEL_CACHE_DIR="${HOME}/.cache/ultratranscribr/models/gguf"
mkdir -p "${MODEL_CACHE_DIR}"

MODEL_FILE="${MODEL_CACHE_DIR}/ggml-large-v3-turbo.bin"
if [[ -f "${MODEL_FILE}" ]] && [[ $(stat -c%s "${MODEL_FILE}" 2>/dev/null || echo 0) -gt 1000000 ]]; then
    SIZE_MB=$(( $(stat -c%s "${MODEL_FILE}") / 1048576 ))
    echo "  Modello gia in cache: ${MODEL_FILE} (${SIZE_MB} MB)"
else
    echo "  Download in corso (circa 1.5 GB, solo la prima volta)..."

    # Metodo 1: wget/curl diretto (piu affidabile per file grandi)
    DOWNLOAD_OK=false

    # URL primario: ggerganov/whisper.cpp (repo pubblico, non richiede auth)
    MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin"

    # URL alternativo: ggml-org/whisper-large-v3-turbo (puo richiedere auth)
    MODEL_URL_ALT="https://huggingface.co/ggml-org/whisper-large-v3-turbo/resolve/main/ggml-large-v3-turbo.bin"

    if command -v wget &>/dev/null; then
        echo "  Tentativo download con wget da ggerganov/whisper.cpp..."
        if wget -c -O "${MODEL_FILE}.tmp" "${MODEL_URL}" 2>&1; then
            mv "${MODEL_FILE}.tmp" "${MODEL_FILE}"
            DOWNLOAD_OK=true
        else
            echo "  Download primario fallito, provo mirror alternativo..."
            rm -f "${MODEL_FILE}.tmp"
            if wget -c -O "${MODEL_FILE}.tmp" "${MODEL_URL_ALT}" 2>&1; then
                mv "${MODEL_FILE}.tmp" "${MODEL_FILE}"
                DOWNLOAD_OK=true
            else
                rm -f "${MODEL_FILE}.tmp"
            fi
        fi
    elif command -v curl &>/dev/null; then
        echo "  Tentativo download con curl da ggerganov/whisper.cpp..."
        if curl -L -C - -o "${MODEL_FILE}.tmp" "${MODEL_URL}" 2>&1; then
            mv "${MODEL_FILE}.tmp" "${MODEL_FILE}"
            DOWNLOAD_OK=true
        else
            echo "  Download primario fallito, provo mirror alternativo..."
            rm -f "${MODEL_FILE}.tmp"
            if curl -L -C - -o "${MODEL_FILE}.tmp" "${MODEL_URL_ALT}" 2>&1; then
                mv "${MODEL_FILE}.tmp" "${MODEL_FILE}"
                DOWNLOAD_OK=true
            else
                rm -f "${MODEL_FILE}.tmp"
            fi
        fi
    fi

    # Metodo 2: Python huggingface-hub come fallback
    if [[ "${DOWNLOAD_OK}" == false ]]; then
        echo "  Download diretto fallito, provo huggingface-hub..."
        "${VENV_DIR}/bin/python" -c "
from huggingface_hub import hf_hub_download

# Prova prima il repo pubblico ggerganov/whisper.cpp
for repo in ['ggerganov/whisper.cpp', 'ggml-org/whisper-large-v3-turbo']:
    try:
        path = hf_hub_download(
            repo_id=repo,
            filename='ggml-large-v3-turbo.bin',
            local_dir='${MODEL_CACHE_DIR}',
        )
        print(f'  Scaricato da {repo}: {path}')
        break
    except Exception as e:
        print(f'  Repo {repo} fallito: {e}')
        continue
else:
    raise RuntimeError('Download fallito da tutti i repository')
" || echo "  ATTENZIONE: Download modello fallito. Sara scaricato al primo avvio."
    else
        SIZE_MB=$(( $(stat -c%s "${MODEL_FILE}") / 1048576 ))
        echo "  Modello scaricato: ${MODEL_FILE} (${SIZE_MB} MB)"
    fi
fi

# ── Fase 7: Verifica driver GPU Intel ──────────────────────────
echo ""
echo "[7/8] Verifica driver GPU Intel Arc..."

GPU_OK=true

# Verifica Level Zero loader
if [[ -f "/usr/lib/libze_loader.so" ]] || [[ -f "/usr/lib64/libze_loader.so" ]] || [[ -f "/lib/libze_loader.so" ]]; then
    echo "  Level Zero loader: OK"
else
    echo "  Level Zero loader: MANCANTE"
    GPU_OK=false
fi

# Verifica Intel Compute Runtime (ocloc)
if command -v ocloc &>/dev/null; then
    echo "  Intel Compute Runtime (ocloc): OK"
else
    echo "  Intel Compute Runtime (ocloc): MANCANTE"
    GPU_OK=false
fi

# Verifica GPU Intel via lspci
if command -v lspci &>/dev/null && lspci | grep -q "VGA compatible controller: Intel"; then
    echo "  GPU Intel rilevata: OK"
else
    echo "  GPU Intel: NON RILEVATA (potrebbe essere integrata e non visibile via lspci)"
fi

if [[ "${GPU_OK}" == false ]]; then
    echo ""
    echo "  ATTENZIONE: Alcuni componenti GPU mancanti."
    echo "  Installare: sudo pacman -S intel-compute-runtime level-zero"
fi

# ── Fase 8: Integrazione Desktop ───────────────────────────────
echo ""
echo "[8/8] Integrazione desktop KDE Plasma..."

# Icona
ICON_PNG="${SCRIPT_DIR}/assets/icons/icon.png"
ICON_SVG="${SCRIPT_DIR}/assets/icons/ultratranscribr.svg"

if [[ -f "${ICON_PNG}" ]]; then
    echo "  Installazione icona PNG..."
    for size in 48 64 128 256; do
        size_dir="${HOME}/.local/share/icons/hicolor/${size}x${size}/apps"
        mkdir -p "${size_dir}"
        if command -v convert &>/dev/null; then
            convert "${ICON_PNG}" -resize "${size}x${size}" "${size_dir}/${APP_ID}.png" 2>/dev/null || \
                cp "${ICON_PNG}" "${size_dir}/${APP_ID}.png"
        else
            cp "${ICON_PNG}" "${size_dir}/${APP_ID}.png"
        fi
    done
fi

mkdir -p "${ICON_SCALABLE_DIR}"
if [[ -f "${ICON_SVG}" ]]; then
    cp "${ICON_SVG}" "${ICON_SCALABLE_DIR}/${APP_ID}.svg"
else
    cat > "${ICON_SCALABLE_DIR}/${APP_ID}.svg" << 'SVGEOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <circle cx="16" cy="16" r="14" fill="#00bfa5"/>
  <text x="16" y="21" text-anchor="middle" fill="#eff0f1"
        font-family="Noto Sans" font-size="14" font-weight="bold">UT</text>
</svg>
SVGEOF
fi

# File .desktop
mkdir -p "$(dirname "${DESKTOP_FILE}")"
cat > "${DESKTOP_FILE}" << EOF
[Desktop Entry]
Type=Application
Name=${APP_NAME}
Comment=Trascrizione audio accelerata GPU Intel Arc (SYCL)
Exec=${VENV_DIR}/bin/python ${SCRIPT_DIR}/main.py %F
Icon=${APP_ID}
Terminal=false
Categories=AudioVideo;Audio;Utility;
Keywords=transcription;whisper;audio;speech;sycl;intel;gpu;
StartupNotify=true
StartupWMClass=${APP_ID}
EOF

# Aggiorna cache
update-desktop-database "$(dirname "${DESKTOP_FILE}")" 2>/dev/null || true
gtk-update-icon-cache -f "$(dirname "${ICON_SCALABLE_DIR}")" 2>/dev/null || true

# Configurazione ld.so.conf per oneAPI
# Aggiunge i percorsi delle librerie runtime oneAPI al sistema
if [[ -d "/opt/intel/oneapi" ]] && [[ ! -f "/etc/ld.so.conf.d/intel-oneapi.conf" ]]; then
    echo "  Configurazione ld.so.conf per Intel oneAPI..."
    # Racchiude tutte le sottodirectory lib di oneAPI
    {
        for d in /opt/intel/oneapi/compiler/*/lib /opt/intel/oneapi/mkl/*/lib /opt/intel/oneapi/tbb/*/lib/intel64/gcc4.8 /opt/intel/oneapi/dnnl/*/lib; do
            [[ -d "$d" ]] && echo "$d"
        done
    } | sudo tee /etc/ld.so.conf.d/intel-oneapi.conf >/dev/null 2>/dev/null || true
    sudo ldconfig 2>/dev/null || true
fi

echo ""
echo "=============================================="
echo "  ${APP_NAME} installato con successo!"
echo "=============================================="
echo ""
echo "  Avvia dal menu applicazioni o con:"
echo "    ${VENV_DIR}/bin/python ${SCRIPT_DIR}/main.py"
echo ""
echo "  Backend: whisper.cpp + SYCL (GPU Intel Arc)"
echo "  Modello: Whisper Large V3 Turbo (FP16)"
echo ""
if [[ "${GPU_OK}" == false ]]; then
    echo "  ATTENZIONE: Installare i driver GPU mancanti prima dell'uso:"
    echo "    sudo pacman -S intel-compute-runtime level-zero"
    echo ""
fi
