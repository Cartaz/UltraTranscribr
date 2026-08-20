# Maintainer: UltraTranscribr
pkgname=ultratranscribr-sycl
pkgver=5.3.0
pkgrel=1
pkgdesc="Trascrizione audio con whisper.cpp SYCL su GPU Intel"
arch=('x86_64')
url="https://github.com/Cartaz/UltraTranscribr"
license=('MIT')
depends=('python' 'python-pyside6' 'python-numpy' 'python-sounddevice' 'python-soundfile'
         'python-pulsectl' 'python-huggingface-hub' 'ffmpeg' 'intel-oneapi-basekit'
         'intel-compute-runtime' 'level-zero')
makedepends=('cmake' 'git')
_wcpp_commit=339f2b4e27d7c3b52f44a124a854abba507acff3
source=("git+https://github.com/ggml-org/whisper.cpp.git#commit=${_wcpp_commit}")
sha256sums=('SKIP')

build() {
  set +u
  source /opt/intel/oneapi/setvars.sh >/dev/null 2>&1 || true
  set -u
  cmake -S whisper.cpp -B whisper.cpp/build -DGGML_SYCL=ON \
    -DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx -DCMAKE_BUILD_TYPE=Release
  cmake --build whisper.cpp/build --config Release -j"$(nproc)"
}

package() {
  app="${pkgdir}/opt/${pkgname}"
  install -d "$app" "${pkgdir}/usr/bin"
  cp -a "${startdir}/config" "${startdir}/core" "${startdir}/ui" \
        "${startdir}/assets" "${startdir}/main.py" "$app/"
  server="$(find whisper.cpp/build -type f -name whisper-server -perm -u+x | head -1)"
  install -Dm755 "$server" "$app/whisper-server"
  install -d "$app/lib"
  while IFS= read -r -d '' so; do cp -L "$so" "$app/lib/"; done < <(find whisper.cpp/build -name 'lib*.so*' -type f -print0)
  cat > "${pkgdir}/usr/bin/${pkgname}" <<EOF
#!/bin/bash
export LD_LIBRARY_PATH="/opt/${pkgname}/lib:\${LD_LIBRARY_PATH:-}"
exec /usr/bin/python /opt/${pkgname}/main.py "\$@"
EOF
  chmod +x "${pkgdir}/usr/bin/${pkgname}"
  install -Dm644 /dev/stdin "${pkgdir}/usr/share/applications/com.ultratranscribr.app.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=UltraTranscribr
Exec=/usr/bin/${pkgname}
Terminal=false
Categories=AudioVideo;Audio;Utility;
EOF
}
