# Maintainer: UltraTranscribr
pkgname=ultratranscribr-sycl
pkgver=5.2.0
pkgrel=1
pkgdesc="Trascrizione audio accelerata GPU Intel Arc (SYCL/whisper.cpp)"
arch=('x86_64')
url="https://github.com/ultratranscribr/ultratranscribr"
license=('MIT')
depends=('python' 'python-pip' 'ffmpeg' 'intel-oneapi-basekit' 'intel-compute-runtime' 'level-zero')
makedepends=('python-setuptools' 'cmake' 'git')
source=("$pkgname-$pkgver.tar.gz")
sha256sums=('SKIP')

package() {
    install -d "${pkgdir}/opt/${pkgname}"
    cp -r "${srcdir}/${pkgname}-${pkgver}/"* "${pkgdir}/opt/${pkgname}/"

    install -d "${pkgdir}/usr/bin"
    cat > "${pkgdir}/usr/bin/${pkgname}" << EOF
#!/bin/bash
exec /opt/${pkgname}/.venv/bin/python /opt/${pkgname}/main.py "\$@"
EOF
    chmod +x "${pkgdir}/usr/bin/${pkgname}"

    install -Dm644 /dev/stdin "${pkgdir}/usr/share/applications/com.ultratranscribr.app.desktop" << EOF
[Desktop Entry]
Type=Application
Name=UltraTranscribr
Comment=Trascrizione audio accelerata GPU Intel Arc (SYCL)
Exec=/usr/bin/${pkgname} %F
Icon=com.ultratranscribr.app
Terminal=false
Categories=AudioVideo;Audio;Utility;
Keywords=transcription;whisper;audio;speech;sycl;intel;gpu;
StartupNotify=true
EOF
}
