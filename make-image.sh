#!/bin/bash
# =============================================================================
# Camera Viewer — Build disco immagine con Podman
#
# Crea un'immagine disco pre-installata (~500MB compressa).
# Il risultato si distribuisce ai clienti che la copiano sulla USB.
#
# Uso:  bash make-image.sh
#
# Requisiti: Podman, curl
# Tempo:     ~20-30 minuti (solo la prima volta)
# Output:    dist/camera-viewer-v2.0.img.xz
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="2.0"
OUTPUT_DIR="$SCRIPT_DIR/dist"
OUTPUT_IMG="$OUTPUT_DIR/camera-viewer-v${VERSION}.img.xz"

# Colori
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

header() {
    clear
    echo -e "${CYAN}${BOLD}"
    echo "  ╔══════════════════════════════════════════════════╗"
    echo "  ║   🎥  Camera Viewer — Image Builder             ║"
    echo "  ║       Creato da Enzo Pellegrino                 ║"
    echo "  ╚══════════════════════════════════════════════════╝"
    echo -e "${RESET}"
}

step()  { echo -e "\n${BOLD}[$1/$TOTAL]${RESET} $2"; }
ok()    { echo -e "  ${GREEN}✓${RESET} $1"; }
warn()  { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
err()   { echo -e "  ${RED}✗ ERRORE:${RESET} $1"; exit 1; }

TOTAL=4

header

# ── Verifica Podman ───────────────────────────────────────────────────────────
step 1 "Verifica requisiti..."
command -v podman &>/dev/null || err "Podman non trovato. Installa con: brew install podman"
ok "Podman trovato: $(podman --version)"

mkdir -p "$OUTPUT_DIR"

# ── Verifica se l'immagine esiste già ────────────────────────────────────────
if [ -f "$OUTPUT_IMG" ]; then
    echo ""
    echo -e "  ${YELLOW}Immagine già esistente:${RESET}"
    ls -lh "$OUTPUT_IMG"
    echo ""
    read -rp "  Ricostruire? [y/N]: " REBUILD
    [[ "$REBUILD" =~ ^[yY]$ ]] || { echo "Annullato."; exit 0; }
fi

# ── Prepara archivio app ──────────────────────────────────────────────────────
step 2 "Preparazione archivio app..."
cd "$SCRIPT_DIR"
APP_TGZ="$OUTPUT_DIR/camera-viewer-app.tar.gz"
tar czf "$APP_TGZ" \
    --exclude='.git' --exclude='.venv' --exclude='dist' \
    --exclude='build' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='*.spec' --exclude='make-image.sh' --exclude='make-usb.sh' .
ok "App: $(ls -lh "$APP_TGZ" | awk '{print $5}')"

# ── Build immagine dentro Podman ──────────────────────────────────────────────
step 3 "Build immagine disco (richiede ~20 min, privileged)..."
echo ""
echo -e "  ${CYAN}Avvio container Podman privilegiato...${RESET}"
echo "  (i log tecnici vengono mostrati durante il build)"
echo ""

podman run --rm --privileged \
    --platform linux/amd64 \
    --security-opt seccomp=unconfined \
    --security-opt apparmor=unconfined \
    --cap-add SYS_ADMIN,MKNOD,NET_ADMIN \
    --name cv-image-builder \
    -v "$OUTPUT_DIR:/output:z" \
    -v "$SCRIPT_DIR/setup:/setup:ro,z" \
    ubuntu:24.04 \
    bash /setup/build_image_inside.sh "$VERSION"

# ── Verifica output ───────────────────────────────────────────────────────────
step 4 "Verifica output..."
if [ -f "$OUTPUT_IMG" ]; then
    SIZE=$(ls -lh "$OUTPUT_IMG" | awk '{print $5}')
    ok "Immagine creata: $OUTPUT_IMG ($SIZE)"

    # Pulizia temporanei
    rm -f "$APP_TGZ"

    echo ""
    echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════╗${RESET}"
    echo -e "${GREEN}${BOLD}║  ✅ Build completato!                            ║${RESET}"
    echo -e "${GREEN}${BOLD}╠══════════════════════════════════════════════════╣${RESET}"
    echo -e "${GREEN}${BOLD}║  File: dist/camera-viewer-v${VERSION}.img.xz       ║${RESET}"
    echo -e "${GREEN}${BOLD}║  Size: $SIZE                                ║${RESET}"
    echo -e "${GREEN}${BOLD}║                                                  ║${RESET}"
    echo -e "${GREEN}${BOLD}║  Per creare la USB:                              ║${RESET}"
    echo -e "${GREEN}${BOLD}║    bash make-usb.sh                              ║${RESET}"
    echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════╝${RESET}"
    echo ""
else
    err "Immagine non trovata in $OUTPUT_IMG"
fi
