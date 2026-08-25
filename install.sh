#!/usr/bin/env bash
# UltraTranscribr installer for CachyOS/Arch + Intel SYCL.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
CACHE="$ROOT/.cache"
WCPP="$CACHE/whisper.cpp"
PIN="339f2b4e27d7c3b52f44a124a854abba507acff3"
ONEAPI="/opt/intel/oneapi"
REQ_MARKER="$VENV/.ultratranscribr-requirements.sha256"
BUILD_MARKER="$VENV/.ultratranscribr-whisper-build.sha256"
FORCE_REBUILD="${ULTRATRANSCRIBR_FORCE_REBUILD:-0}"

log() { printf '[UltraTranscribr] %s\n' "$*"; }
die() { printf 'ERRORE: %s\n' "$*" >&2; exit 1; }

find_python() {
  local candidate
  for candidate in python3.13 python3.12 python3; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 12) else 1)
PY
    then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

requirements_imports_ok() {
  "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import PySide6
import huggingface_hub
import numpy
import pulsectl
import sounddevice
import soundfile
PY
}

requirements_key() {
  {
    "$VENV/bin/python" --version 2>&1
    sha256sum "$ROOT/requirements.txt"
  } | sha256sum | awk '{print $1}'
}

build_key() {
  {
    printf '%s\n' "$PIN"
    printf '%s\n' 'GGML_SYCL=ON|Release|icx|icpx'
    icx --version | head -1
    icpx --version | head -1
    cmake --version | head -1
  } | sha256sum | awk '{print $1}'
}

ask_demucs() {
  local mode="${ULTRATRANSCRIBR_INSTALL_DEMUCS:-ask}"
  case "${mode,,}" in
    1|true|yes|y|s) return 0 ;;
    0|false|no|n) return 1 ;;
    ask)
      if [[ -t 0 ]]; then
        local answer=""
        read -r -p "Installare Demucs + PyTorch CPU per modalità Musica? [s/N]: " answer || true
        [[ "$answer" =~ ^[sSyY]$ ]]
        return
      fi
      return 1
      ;;
    *) die "ULTRATRANSCRIBR_INSTALL_DEMUCS deve essere ask, 1 oppure 0" ;;
  esac
}

install_python_dependencies() {
  local key
  key="$(requirements_key)"
  if [[ -f "$REQ_MARKER" ]] \
     && [[ "$(cat "$REQ_MARKER")" == "$key" ]] \
     && requirements_imports_ok; then
    log "Dipendenze Python invariate: salto pip install."
    return
  fi

  log "Installazione/aggiornamento dipendenze Python..."
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/pip" install -r "$ROOT/requirements.txt"
  requirements_imports_ok || die "Verifica import dipendenze Python fallita"
  key="$(requirements_key)"
  printf '%s\n' "$key" > "$REQ_MARKER"
}

install_optional_demucs() {
  ask_demucs || return 0
  if "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import demucs
import torch
PY
  then
    log "Demucs già installato: nessuna modifica."
    return
  fi

  log "Installazione Demucs + PyTorch CPU..."
  "$VENV/bin/pip" install --index-url https://download.pytorch.org/whl/cpu torch torchaudio
  "$VENV/bin/pip" install demucs
}

whisper_build_is_current() {
  local key="$1"
  [[ "$FORCE_REBUILD" != "1" ]] || return 1
  [[ -x "$VENV/bin/whisper-server" ]] || return 1
  [[ -f "$BUILD_MARKER" ]] || return 1
  [[ "$(cat "$BUILD_MARKER")" == "$key" ]] || return 1
  compgen -G "$VENV/lib/libggml-sycl.so*" >/dev/null || return 1
  "$VENV/bin/whisper-server" --help >/dev/null 2>&1 || return 1
  return 0
}

prepare_whisper_source() {
  mkdir -p "$CACHE"
  if [[ ! -d "$WCPP/.git" ]]; then
    rm -rf "$WCPP"
    git clone https://github.com/ggml-org/whisper.cpp.git "$WCPP"
  fi

  local current=""
  current="$(git -C "$WCPP" rev-parse HEAD 2>/dev/null || true)"
  if [[ "$current" != "$PIN" ]]; then
    git -C "$WCPP" fetch --depth 1 origin "$PIN" \
      || die "Impossibile scaricare commit whisper.cpp $PIN"
    git -C "$WCPP" checkout --detach "$PIN" \
      || die "Checkout whisper.cpp fallito"
  fi
}

build_whisper_server() {
  local key="$1"
  if whisper_build_is_current "$key"; then
    log "whisper.cpp/SYCL invariato: salto configurazione e build."
    return
  fi

  log "Build whisper.cpp SYCL richiesta."
  prepare_whisper_source
  rm -rf "$WCPP/build"
  cmake -S "$WCPP" -B "$WCPP/build" \
    -DGGML_SYCL=ON \
    -DCMAKE_C_COMPILER=icx \
    -DCMAKE_CXX_COMPILER=icpx \
    -DCMAKE_BUILD_TYPE=Release \
    || die "Configurazione CMake fallita"
  cmake --build "$WCPP/build" --config Release -j"$(nproc)" \
    || die "Build whisper.cpp fallita"

  local server
  server="$(find "$WCPP/build" -type f -name whisper-server -perm -u+x | head -1)"
  [[ -n "$server" ]] || die "whisper-server non trovato nella build"
  install -Dm755 "$server" "$VENV/bin/whisper-server"

  mkdir -p "$VENV/lib"
  rm -f "$VENV/lib"/libggml*.so* "$VENV/lib"/libwhisper.so* 2>/dev/null || true
  while IFS= read -r -d '' so; do
    cp -L "$so" "$VENV/lib/"
  done < <(find "$WCPP/build" -name 'lib*.so*' -type f -print0)

  export LD_LIBRARY_PATH="$VENV/lib:${LD_LIBRARY_PATH:-}"
  "$VENV/bin/whisper-server" --help >/dev/null 2>&1 \
    || die "whisper-server non eseguibile"
  printf '%s\n' "$key" > "$BUILD_MARKER"
}

ensure_default_models() {
  cd "$ROOT"
  "$VENV/bin/python" - <<'PY'
from core.whisper_models import WhisperModelManager

manager = WhisperModelManager()
print("ASR:", manager.get_model_path("large-v3-turbo"))
print("VAD:", manager.get_vad_model_path())
PY
}

install_desktop_entry() {
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
}

run_environment_check() {
  cd "$ROOT"
  export LD_LIBRARY_PATH="$VENV/lib:${LD_LIBRARY_PATH:-}"
  "$VENV/bin/python" -m core.environment_check \
    || die "Self-check finale fallito. Consulta il report sopra."
}

main() {
  echo "=== UltraTranscribr / Intel SYCL ==="

  local py
  py="$(find_python)" || die "Python 3.12+ non trovato"
  [[ -f "$ONEAPI/setvars.sh" ]] || die "Intel oneAPI non trovato in $ONEAPI"
  command -v git >/dev/null || die "git non trovato"
  command -v cmake >/dev/null || die "cmake non trovato"
  command -v ffmpeg >/dev/null || die "ffmpeg non trovato"
  command -v sha256sum >/dev/null || die "sha256sum non trovato"

  if [[ ! -x "$VENV/bin/python" ]] || ! "$VENV/bin/python" -V >/dev/null 2>&1; then
    log "Creo ambiente virtuale Python."
    rm -rf "$VENV"
    "$py" -m venv "$VENV"
  fi

  install_python_dependencies
  install_optional_demucs

  set +u
  # shellcheck disable=SC1091
  source "$ONEAPI/setvars.sh" >/dev/null 2>&1 || true
  set -u
  command -v icx >/dev/null || die "icx non disponibile dopo setvars.sh"
  command -v icpx >/dev/null || die "icpx non disponibile dopo setvars.sh"

  local key
  key="$(build_key)"
  build_whisper_server "$key"
  ensure_default_models
  install_desktop_entry
  chmod +x "$ROOT/install.sh"
  run_environment_check

  echo "Installazione completata."
  echo "Avvio: $VENV/bin/python $ROOT/main.py"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
