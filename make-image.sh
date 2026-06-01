#!/bin/bash
# =============================================================================
# Camera Viewer — Build immagine Live USB
# Creato da Enzo Pellegrino
#
# Usa la VM Linux di Podman (non il container) per le operazioni privilegiate.
# La VM ha accesso diretto ai loop device — nessun problema di permessi.
#
# Uso: bash make-image.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="2.0"
OUTPUT_DIR="$SCRIPT_DIR/dist"
OUTPUT_IMG="$OUTPUT_DIR/camera-viewer-v${VERSION}.img.xz"
APP_TGZ="$OUTPUT_DIR/camera-viewer-app.tar.gz"
SETUP_SCRIPT="$SCRIPT_DIR/setup/build_image_inside.sh"

# Colori
R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; C='\033[0;36m'; B='\033[1m'; E='\033[0m'

hdr() {
    clear
    echo -e "${C}${B}"
    echo "  ╔══════════════════════════════════════════════════╗"
    echo "  ║   🎥  Camera Viewer v${VERSION} — Image Builder     ║"
    echo "  ║       Creato da Enzo Pellegrino                 ║"
    echo "  ╚══════════════════════════════════════════════════╝"
    echo -e "${E}"
}

ok()   { echo -e "  ${G}✓${E} $1"; }
warn() { echo -e "  ${Y}⚠${E}  $1"; }
err()  { echo -e "  ${R}✗ ERRORE:${E} $1"; exit 1; }
step() { echo -e "\n${B}[$1/$TOTAL]${E} $2"; }
TOTAL=5

hdr

# ── Step 1: Verifica Podman ───────────────────────────────────────────────────
step 1 "Verifica Podman..."
command -v podman &>/dev/null || err "Podman non trovato"
ok "Podman $(podman --version | awk '{print $3}')"

# Avvia la VM di Podman se non è attiva
VM_STATE=$(podman machine inspect --format '{{.State}}' 2>/dev/null | head -1 || echo "stopped")
if [[ "$VM_STATE" != "running" ]]; then
    echo "  → Avvio VM Podman..."
    podman machine start
    sleep 5
fi
ok "VM Podman attiva"

# Verifica che la VM monti la home directory
# (Podman machine monta /Users automaticamente su macOS)
VM_MOUNT=$(podman machine ssh "ls '$SCRIPT_DIR/setup/build_image_inside.sh' 2>/dev/null && echo OK || echo MISSING" 2>/dev/null || echo "MISSING")
if [[ "$VM_MOUNT" != "OK" ]]; then
    err "La VM Podman non può accedere a $SCRIPT_DIR\n  Verifica che la home directory sia montata nella VM."
fi
ok "File accessibili dalla VM"

# ── Step 2: Prepara archivio app ─────────────────────────────────────────────
step 2 "Creazione archivio app..."
mkdir -p "$OUTPUT_DIR"
cd "$SCRIPT_DIR"
tar czf "$APP_TGZ" \
    --exclude='.git' --exclude='.venv' --exclude='dist' \
    --exclude='build' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='*.spec' --exclude='make-image.sh' --exclude='make-usb.sh' .
ok "App: $(ls -lh "$APP_TGZ" | awk '{print $5}')"

# ── Step 3: Build dentro la VM Podman (loop device disponibili!) ──────────────
step 3 "Build immagine nella VM Podman (~20-30 min)..."
echo ""
echo -e "  ${C}La VM Linux ha accesso diretto ai loop device.${E}"
echo "  I log vengono mostrati in tempo reale:"
echo ""

# Esegui lo script di build DENTRO la VM (non in un container)
# La VM è un sistema Linux reale con tutti i permessi necessari
podman machine ssh "sudo bash '$SETUP_SCRIPT' '$VERSION' '$OUTPUT_DIR' '$APP_TGZ'"

# ── Step 4: Verifica ─────────────────────────────────────────────────────────
step 4 "Verifica output..."
if [ -f "$OUTPUT_IMG" ]; then
    SIZE=$(ls -lh "$OUTPUT_IMG" | awk '{print $5}')
    ok "Immagine: dist/camera-viewer-v${VERSION}.img.xz ($SIZE)"
else
    err "Immagine non trovata: $OUTPUT_IMG"
fi

# ── Step 5: Pulizia ───────────────────────────────────────────────────────────
step 5 "Pulizia file temporanei..."
rm -f "$APP_TGZ"
ok "Pulizia completata"

echo ""
echo -e "${G}${B}╔══════════════════════════════════════════════════╗${E}"
echo -e "${G}${B}║  ✅ Build completato!                            ║${E}"
echo -e "${G}${B}╠══════════════════════════════════════════════════╣${E}"
echo -e "${G}${B}║  File:  dist/camera-viewer-v${VERSION}.img.xz       ║${E}"
echo -e "${G}${B}║  Size:  $SIZE                                    ║${E}"
echo -e "${G}${B}║                                                  ║${E}"
echo -e "${G}${B}║  Per creare una USB:                             ║${E}"
echo -e "${G}${B}║    bash make-usb.sh                              ║${E}"
echo -e "${G}${B}╚══════════════════════════════════════════════════╝${E}"
echo ""
