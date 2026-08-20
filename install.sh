#!/usr/bin/env bash
# UltraTranscribr installer for CachyOS/Arch + Intel SYCL.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"; CACHE="$ROOT/.cache"; WCPP="$CACHE/whisper.cpp"
PIN="339f2b4e27d7c3b52f44a124a854abba507acff3"
ONEAPI="/opt/intel/oneapi"
die(){ echo "ERRORE: $*" >&2; exit 1; }
echo "=== UltraTranscribr / Intel SYCL ==="
PY=""
for x in python3.13 python3.12 python3.11 python3; do
  command -v "$x" >/dev/null 2>&1 || continue
  "$x" - <<'PY' >/dev/null 2>&1 && { PY="$x"; break; }
import sys
raise SystemExit(0 if sys.version_info >= (3,11) else 1)
PY
done
[[ -n "$PY" ]] || die "Python 3.11+ non trovato"
[[ -f "$ONEAPI/setvars.sh" ]] || die "Intel oneAPI non trovato in $ONEAPI"
command -v git >/dev/null || die "git non trovato"
command -v cmake >/dev/null || die "cmake non trovato"
command -v ffmpeg >/dev/null || die "ffmpeg non trovato"
[[ -d "$VENV" ]] || "$PY" -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$ROOT/requirements.txt"
read -r -p "Installare Demucs + PyTorch CPU per modalità Musica? [s/N]: " DEMUCS || true
if [[ "${DEMUCS:-}" =~ ^[sSyY]$ ]]; then
  "$VENV/bin/pip" install --index-url https://download.pytorch.org/whl/cpu torch torchaudio
  "$VENV/bin/pip" install demucs
fi
set +u
source "$ONEAPI/setvars.sh" >/dev/null 2>&1 || true
set -u
command -v icx >/dev/null || die "icx non disponibile dopo setvars.sh"
command -v icpx >/dev/null || die "icpx non disponibile dopo setvars.sh"
mkdir -p "$CACHE"
if [[ ! -d "$WCPP/.git" ]]; then
  rm -rf "$WCPP"
  git clone https://github.com/ggml-org/whisper.cpp.git "$WCPP"
fi
git -C "$WCPP" fetch --depth 1 origin "$PIN" || die "Impossibile scaricare commit whisper.cpp $PIN"
git -C "$WCPP" checkout --detach "$PIN" || die "Checkout whisper.cpp fallito"
rm -rf "$WCPP/build"
cmake -S "$WCPP" -B "$WCPP/build" -DGGML_SYCL=ON -DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx -DCMAKE_BUILD_TYPE=Release || die "Configurazione CMake fallita"
cmake --build "$WCPP/build" --config Release -j"$(nproc)" || die "Build whisper.cpp fallita"
SERVER="$(find "$WCPP/build" -type f -name whisper-server -perm -u+x | head -1)"
[[ -n "$SERVER" ]] || die "whisper-server non trovato nella build"
install -Dm755 "$SERVER" "$VENV/bin/whisper-server"
mkdir -p "$VENV/lib"
while IFS= read -r -d '' so; do cp -L "$so" "$VENV/lib/"; done < <(find "$WCPP/build" -name 'lib*.so*' -type f -print0)
export LD_LIBRARY_PATH="$VENV/lib:${LD_LIBRARY_PATH:-}"
"$VENV/bin/whisper-server" --help >/dev/null 2>&1 || die "whisper-server non eseguibile"
cd "$ROOT"
"$VENV/bin/python" - <<'PY'
from core.whisper_models import WhisperModelManager
m=WhisperModelManager()
print("ASR:",m.get_model_path("large-v3-turbo"))
print("VAD:",m.get_vad_model_path())
PY
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/com.ultratranscribr.app.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=UltraTranscribr
Comment=Trascrizione audio accelerata Intel SYCL
Exec=$VENV/bin/python $ROOT/main.py
Path=$ROOT
Terminal=false
Categories=AudioVideo;Audio;Utility;
StartupNotify=true
EOF
chmod +x "$ROOT/install.sh"
echo "Installazione completata."
echo "Avvio: $VENV/bin/python $ROOT/main.py"
