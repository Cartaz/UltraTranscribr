#!/usr/bin/env bash
# UltraTranscribr installer for CachyOS/Arch + Intel SYCL/XPU.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
CACHE="$ROOT/.cache"
WCPP="$CACHE/whisper.cpp"
PIN="339f2b4e27d7c3b52f44a124a854abba507acff3"
ONEAPI="/opt/intel/oneapi"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
REQ_MARKER="$VENV/.ultratranscribr-requirements.sha256"
BUILD_MARKER="$VENV/.ultratranscribr-whisper-build.sha256"
FORCE_REBUILD="${ULTRATRANSCRIBR_FORCE_REBUILD:-0}"
TORCH_VERSION="2.9.1"
TORCHAUDIO_VERSION="2.9.1"
TORCHCODEC_VERSION="0.9.1"
PYTORCH_XPU_INDEX="https://download.pytorch.org/whl/xpu"
PYTORCH_CPU_INDEX="https://download.pytorch.org/whl/cpu"

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

_requirements_imports_probe() {
  "$VENV/bin/python" - <<PY
from importlib.metadata import version

import PySide6
import dbus_next
import demucs_infer
import huggingface_hub
import numpy
import pulsectl
import pyannote.audio
import sounddevice
import soundfile
import torch
import torchaudio

assert version("torch").split("+")[0] == "$TORCH_VERSION"
assert version("torchaudio").split("+")[0] == "$TORCHAUDIO_VERSION"
# TorchCodec is a declared pyannote dependency, but UltraTranscribr passes
# already-decoded waveforms to Community-1 and never invokes TorchCodec.
# Validate the installed distribution version without loading its native codec
# extension, which may legitimately be unavailable with the XPU torch build.
assert version("torchcodec").split("+")[0] == "$TORCHCODEC_VERSION"
assert "+xpu" in torch.__version__, torch.__version__
PY
}

requirements_imports_ok() {
  if [[ "${1:-quiet}" == "verbose" ]]; then
    _requirements_imports_probe
  else
    _requirements_imports_probe >/dev/null 2>&1
  fi
}

requirements_key() {
  {
    "$VENV/bin/python" --version 2>&1
    printf '%s\n' "$TORCH_VERSION" "$TORCHAUDIO_VERSION" "$TORCHCODEC_VERSION"
    sha256sum "$ROOT/requirements.txt" "$ROOT/requirements-xpu.txt"
  } | sha256sum | awk '{print $1}'
}

build_key() {
  {
    printf '%s\n' "$PIN"
    printf '%s\n' 'GGML_SYCL=ON|Release|icx|icpx|server-only'
    icx --version | head -1
    icpx --version | head -1
    cmake --version | head -1
  } | sha256sum | awk '{print $1}'
}

install_python_dependencies() {
  local key
  key="$(requirements_key)"
  if [[ -f "$REQ_MARKER" ]] \
     && [[ "$(cat "$REQ_MARKER")" == "$key" ]] \
     && requirements_imports_ok; then
    log "Dipendenze Python/XPU invariate: salto pip install."
    return
  fi

  log "Installazione/aggiornamento dipendenze Python..."
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/pip" install -r "$ROOT/requirements.txt"

  log "Installazione PyTorch Intel XPU $TORCH_VERSION..."
  "$VENV/bin/pip" install --index-url "$PYTORCH_XPU_INDEX" \
    "torch==$TORCH_VERSION" "torchaudio==$TORCHAUDIO_VERSION"

  # pyannote.audio declares TorchCodec, but UltraTranscribr passes already-decoded
  # waveforms to the diarizer. The CPU codec wheel satisfies dependency metadata
  # without introducing a second GPU media stack; it is not imported by our runtime.
  "$VENV/bin/pip" install --no-deps --index-url "$PYTORCH_CPU_INDEX" \
    "torchcodec==$TORCHCODEC_VERSION"

  log "Installazione diarizzazione Community-1 e Demucs..."
  "$VENV/bin/pip" install -r "$ROOT/requirements-xpu.txt"

  requirements_imports_ok verbose \
    || die "Verifica dipendenze PyTorch XPU/pyannote/Demucs fallita"
  key="$(requirements_key)"
  printf '%s\n' "$key" > "$REQ_MARKER"
}

verify_installed_whisper() {
  cd "$ROOT"
  env -u LD_LIBRARY_PATH "$VENV/bin/python" - "$VENV/bin/whisper-server" <<'PY'
import sys
from pathlib import Path

from core.whisper_gpu_detect import verify_sycl_binary

binary = sys.argv[1]
raise SystemExit(0 if verify_sycl_binary(binary, Path.cwd()) else 1)
PY
}

whisper_build_is_current() {
  local key="$1"
  [[ "$FORCE_REBUILD" != "1" ]] || return 1
  [[ -x "$VENV/bin/whisper-server" ]] || return 1
  [[ -f "$BUILD_MARKER" ]] || return 1
  [[ "$(cat "$BUILD_MARKER")" == "$key" ]] || return 1
  compgen -G "$VENV/lib/libggml-sycl.so*" >/dev/null || return 1
  verify_installed_whisper >/dev/null 2>&1 || return 1
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

package_whisper_runtime() {
  local build_bin="$WCPP/build/bin"
  local server="$build_bin/whisper-server"
  [[ -x "$server" ]] || die "whisper-server non trovato nella build"

  install -Dm755 "$server" "$VENV/bin/whisper-server"
  mkdir -p "$VENV/lib"
  rm -f "$VENV/lib"/libggml*.so* "$VENV/lib"/libwhisper.so* 2>/dev/null || true

  local copied=0
  while IFS= read -r -d '' library; do
    cp -a "$library" "$VENV/lib/"
    copied=1
  done < <(
    find "$build_bin" -maxdepth 1 -name 'lib*.so*' \
      \( -type f -o -type l \) -print0
  )
  [[ "$copied" == "1" ]] || die "Librerie whisper.cpp non trovate nella build"
  compgen -G "$VENV/lib/libggml-sycl.so*" >/dev/null \
    || die "libggml-sycl non installata"
}

build_whisper_server() {
  local key="$1"
  if whisper_build_is_current "$key"; then
    log "whisper.cpp/SYCL invariato: salto configurazione e build."
    return
  fi

  log "Build whisper.cpp SYCL richiesta."
  prepare_whisper_source
  if [[ "$FORCE_REBUILD" == "1" ]]; then
    rm -rf "$WCPP/build"
  fi

  cmake -S "$WCPP" -B "$WCPP/build" \
    -DGGML_SYCL=ON \
    -DWHISPER_BUILD_TESTS=OFF \
    -DWHISPER_BUILD_EXAMPLES=ON \
    -DWHISPER_BUILD_SERVER=ON \
    -DCMAKE_C_COMPILER=icx \
    -DCMAKE_CXX_COMPILER=icpx \
    -DCMAKE_BUILD_TYPE=Release \
    || die "Configurazione CMake fallita"
  cmake --build "$WCPP/build" --target whisper-server --config Release -j"$(nproc)" \
    || die "Build whisper.cpp fallita"

  package_whisper_runtime
  if ! verify_installed_whisper; then
    die "whisper-server SYCL non eseguibile con il runtime oneAPI corrente"
  fi
  printf '%s\n' "$key" > "$BUILD_MARKER"
}

build_whisper_stack() (
  # oneAPI is scoped to this subshell. The Python/PyTorch process must not
  # inherit its LD_LIBRARY_PATH because PyTorch XPU ships its own Intel runtime.
  set +u
  # shellcheck disable=SC1091
  source "$ONEAPI/setvars.sh" >/dev/null 2>&1 \
    || die "Inizializzazione Intel oneAPI fallita"
  set -u
  command -v icx >/dev/null || die "icx non disponibile dopo setvars.sh"
  command -v icpx >/dev/null || die "icpx non disponibile dopo setvars.sh"

  local key
  key="$(build_key)"
  build_whisper_server "$key"
)

ensure_default_models() {
  cd "$ROOT"
  "$VENV/bin/python" - <<'PY'
from config.constants import ProcessDefaults
from core.whisper_models import WhisperModelManager

manager = WhisperModelManager()
print("ASR:", manager.get_model_path(ProcessDefaults.MODEL_SIZE))
print("VAD:", manager.get_vad_model_path())
PY
}

install_desktop_integration() {
  local applications_dir="$DATA_HOME/applications"
  local icon_root="$DATA_HOME/icons/hicolor"
  local icon_source="$ROOT/assets/icons/ultratranscribr.svg"

  [[ -f "$icon_source" ]] || die "Icona desktop mancante: $icon_source"
  install -Dm644 "$icon_source" "$icon_root/scalable/apps/ultratranscribr.svg"
  install -Dm644 "$icon_source" "$icon_root/scalable/status/ultratranscribr.svg"

  mkdir -p "$applications_dir"
  cat > "$applications_dir/com.ultratranscribr.app.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=UltraTranscribr
Comment=Trascrizione audio accelerata Intel SYCL/XPU
Exec=$VENV/bin/python $ROOT/main.py
Path=$ROOT
Icon=ultratranscribr
Terminal=false
Categories=AudioVideo;Audio;Utility;
StartupNotify=true
EOF

  if command -v update-desktop-database >/dev/null 2>&1; then
    if ! update-desktop-database "$applications_dir" >/dev/null 2>&1; then
      log "AVVISO: aggiornamento database .desktop non riuscito; il file è comunque installato."
    fi
  fi

  if command -v kbuildsycoca6 >/dev/null 2>&1; then
    if ! kbuildsycoca6 --noincremental >/dev/null 2>&1; then
      log "AVVISO: refresh cache KDE non riuscito; Plasma lo aggiornerà automaticamente."
    fi
  fi
}

run_environment_check() {
  cd "$ROOT"
  # PyTorch XPU must resolve its wheel-provided Intel runtime. The environment
  # checker launches whisper-server separately with the isolated oneAPI env.
  env -u LD_LIBRARY_PATH \
    ONEAPI_DEVICE_SELECTOR="level_zero:0" \
    "$VENV/bin/python" -m core.environment_check \
    || die "Self-check finale fallito. Consulta il report sopra."
}

main() {
  echo "=== UltraTranscribr / Intel SYCL + PyTorch XPU ==="

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
  build_whisper_stack
  ensure_default_models
  install_desktop_integration
  chmod +x "$ROOT/install.sh"
  run_environment_check

  echo "Installazione completata."
  echo "Avvio: $VENV/bin/python $ROOT/main.py"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
