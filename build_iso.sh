#!/bin/bash
# =============================================================================
# Camera Viewer — Build ISO (Mac wrapper)
#
# Lancia setup/build_image_inside.sh dentro un container Docker Linux
# privilegiato. Richiede Docker Desktop installato e avviato.
#
# Uso:
#   ./build_iso.sh [VERSION]
#   ./build_iso.sh 3.1
#
# Output: dist-iso/camera-viewer-vX.X.iso (~700-900MB)
# =============================================================================
set -euo pipefail

VERSION="${1:-3.0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/dist-iso"

R='\033[0;31m'; G='\033[0;32m'; C='\033[0;36m'; B='\033[1m'; E='\033[0m'

echo ""
echo -e "${C}${B}  ╔══════════════════════════════════════════════════╗${E}"
echo -e "${C}${B}  ║   Camera Viewer v${VERSION} — ISO Builder (Mac)    ║${E}"
echo -e "${C}${B}  ╚══════════════════════════════════════════════════╝${E}"
echo ""

# ── Rileva container runtime (Docker o Podman) ────────────────────────────────
RUNTIME=""
if docker info >/dev/null 2>&1; then
    RUNTIME="docker"
    VERSION_INFO=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo 'ok')
elif podman info >/dev/null 2>&1; then
    RUNTIME="podman"
    VERSION_INFO=$(podman version --format '{{.Server.Version}}' 2>/dev/null || echo 'ok')
else
    echo -e "  ${R}Né Docker né Podman trovati o avviati.${E}"
    echo "  Installa Docker Desktop: https://www.docker.com/products/docker-desktop/"
    echo "  oppure Podman Desktop:   https://podman-desktop.io/"
    exit 1
fi
echo -e "  ${G}✓${E} Runtime: ${RUNTIME} ${VERSION_INFO}"

# Mac Apple Silicon (arm64): serve --platform linux/amd64 per buildare x86_64
PLATFORM_FLAG=""
if [[ "$(uname -m)" == "arm64" ]]; then
    PLATFORM_FLAG="--platform linux/amd64"
    echo -e "  ${C}→${E} Apple Silicon rilevato — build x86_64 via emulazione QEMU"
fi

mkdir -p "$OUTPUT_DIR"

# ── Tarball app ───────────────────────────────────────────────────────────────
APP_TGZ="$OUTPUT_DIR/camera-viewer-app.tar.gz"
echo -e "  ${C}→${E} Creazione tarball app..."
tar czf "$APP_TGZ" \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.venv' \
    --exclude='dist' \
    --exclude='build' \
    --exclude='dist-iso' \
    --exclude='*.iso' \
    --exclude='*.img' \
    --exclude='*.img.xz' \
    -C "$SCRIPT_DIR" .
echo -e "  ${G}✓${E} Tarball: $(ls -lh "$APP_TGZ" | awk '{print $5}')"
echo ""
echo -e "  ${B}Avvio build in Docker (30-40 min)...${E}"
echo -e "  Output: ${OUTPUT_DIR}/camera-viewer-v${VERSION}.iso"
echo ""

# ── Build nel container ───────────────────────────────────────────────────────
# --privileged: necessario per mount --bind nel chroot (debootstrap)
# --platform linux/amd64: su Apple Silicon emula x86_64 via QEMU
# ubuntu:24.04: stessa base dell'immagine prodotta, evita sorprese
$RUNTIME run --rm --privileged $PLATFORM_FLAG \
    -v "$SCRIPT_DIR:/workspace:ro" \
    -v "$OUTPUT_DIR:/output" \
    ubuntu:24.04 \
    bash -c "
        set -e
        cp /output/camera-viewer-app.tar.gz /tmp/camera-viewer-app.tar.gz
        bash /workspace/setup/build_image_inside.sh \
            '${VERSION}' \
            '/output' \
            '/tmp/camera-viewer-app.tar.gz'
    "

# ── Risultato ─────────────────────────────────────────────────────────────────
echo ""
ISO="$OUTPUT_DIR/camera-viewer-v${VERSION}.iso"
if [ -f "$ISO" ]; then
    SIZE=$(ls -lh "$ISO" | awk '{print $5}')
    echo -e "${G}${B}  ╔══════════════════════════════════════════════════════════╗${E}"
    echo -e "${G}${B}  ║  ✅ ISO pronta!                                          ║${E}"
    echo -e "${G}${B}  ╠══════════════════════════════════════════════════════════╣${E}"
    printf "${G}${B}  ║  File: %-50s║${E}\n" "dist-iso/camera-viewer-v${VERSION}.iso"
    printf "${G}${B}  ║  Size: %-50s║${E}\n" "${SIZE}"
    echo -e "${G}${B}  ╠══════════════════════════════════════════════════════════╣${E}"
    echo -e "${G}${B}  ║  Scrivi su USB:                                          ║${E}"
    echo -e "${G}${B}  ║    Balena Etcher — trascina il file .iso (GUI)           ║${E}"
    echo -e "${G}${B}  ║    Rufus — Windows                                       ║${E}"
    echo -e "${G}${B}  ║    dd if=*.iso of=/dev/rdiskX bs=4m  (Mac/Linux)        ║${E}"
    echo -e "${G}${B}  ╚══════════════════════════════════════════════════════════╝${E}"
    echo ""
else
    echo -e "${R}  ✗ Build fallita — controlla l'output sopra.${E}"
    exit 1
fi
