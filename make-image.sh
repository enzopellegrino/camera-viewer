#!/bin/bash
# =============================================================================
# Camera Viewer — Build immagine Live USB (tramite NUC)
#
# Usa il NUC come build host (Ubuntu x86_64 reale) invece di Podman.
# Nessun problema di GRUB, loop device, container o architettura.
#
# Prerequisiti: NUC acceso e raggiungibile via SSH
#
# Uso:
#   bash make-image.sh [IP_NUC]
#   bash make-image.sh               # usa camera-viewer.local
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="2.0"
OUTPUT_DIR="$SCRIPT_DIR/dist"
OUTPUT_IMG="$OUTPUT_DIR/camera-viewer-v${VERSION}.img.xz"
APP_TGZ="$OUTPUT_DIR/camera-viewer-app.tar.gz"
BUILD_SCRIPT="$SCRIPT_DIR/setup/build_image_inside.sh"

NUC_IP="${1:-}"
NUC_USER="pi"
NUC_PASS="N1computer@2019"

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
    echo "  Builder: NUC (Ubuntu x86_64 reale — GRUB garantito)"
    echo ""
}

ok()   { echo -e "  ${G}✓${E} $1"; }
warn() { echo -e "  ${Y}⚠${E}  $1"; }
err()  { echo -e "  ${R}✗ ERRORE:${E} $1"; exit 1; }
step() { echo -e "\n${B}[$1/$TOTAL]${E} $2"; }
TOTAL=5

hdr

# ── Trova IP NUC ──────────────────────────────────────────────────────────────
if [ -z "$NUC_IP" ]; then
    echo -e "  Ricerca NUC in rete..."
    NUC_IP=$(python3 -c "import socket; print(socket.gethostbyname('camera-viewer.local'))" 2>/dev/null || true)
    if [ -z "$NUC_IP" ]; then
        # Scan veloce
        for ip in $(seq 1 254); do
            (ping -c1 -W1 "192.168.10.$ip" &>/dev/null && \
             nc -z -w1 "192.168.10.$ip" 22 2>/dev/null && \
             sshpass -p "$NUC_PASS" ssh -o StrictHostKeyChecking=no \
                 -o PasswordAuthentication=yes -o PubkeyAuthentication=no \
                 -o ConnectTimeout=2 "$NUC_USER@192.168.10.$ip" \
                 "hostname | grep -q camera-viewer && echo 192.168.10.$ip" 2>/dev/null) &
        done
        wait
        NUC_IP=$(jobs -p | xargs -I{} wait {} 2>/dev/null || true)
    fi
    [ -z "$NUC_IP" ] && read -rp "  Inserisci IP del NUC: " NUC_IP
fi

SSH_OPTS=(-o StrictHostKeyChecking=no -o PasswordAuthentication=yes -o PubkeyAuthentication=no)
SCP_OPTS=(-o StrictHostKeyChecking=no -o PasswordAuthentication=yes -o PubkeyAuthentication=no)

# ── Step 1: Verifica NUC ──────────────────────────────────────────────────────
step 1 "Connessione al NUC ($NUC_IP)..."
HOSTNAME=$(sshpass -p "$NUC_PASS" ssh "${SSH_OPTS[@]}" "$NUC_USER@$NUC_IP" "hostname" 2>/dev/null) \
    || err "NUC non raggiungibile su $NUC_IP"
ok "NUC: $HOSTNAME ($NUC_IP)"

DISK_FREE=$(sshpass -p "$NUC_PASS" ssh "${SSH_OPTS[@]}" "$NUC_USER@$NUC_IP" \
    "df -BG / | tail -1 | awk '{print \$4}'" 2>/dev/null)
ok "Spazio libero NUC: $DISK_FREE"

# ── Step 2: Prepara archivio app ──────────────────────────────────────────────
step 2 "Creazione archivio app..."
mkdir -p "$OUTPUT_DIR"
cd "$SCRIPT_DIR"
tar czf "$APP_TGZ" \
    --exclude='.git' --exclude='.venv' --exclude='dist' \
    --exclude='build' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='*.spec' --exclude='make-image.sh' --exclude='make-usb.sh' \
    --exclude='fix-usb-on-nuc.sh' .
ok "App: $(ls -lh "$APP_TGZ" | awk '{print $5}')"

# ── Step 3: Copia file sul NUC ────────────────────────────────────────────────
step 3 "Copia file sul NUC..."
sshpass -p "$NUC_PASS" ssh "${SSH_OPTS[@]}" "$NUC_USER@$NUC_IP" \
    "mkdir -p /tmp/cv-build /tmp/cv-output"

sshpass -p "$NUC_PASS" scp "${SCP_OPTS[@]}" \
    "$BUILD_SCRIPT"  "$NUC_USER@$NUC_IP:/tmp/cv-build/build_image_inside.sh"
sshpass -p "$NUC_PASS" scp "${SCP_OPTS[@]}" \
    "$APP_TGZ"       "$NUC_USER@$NUC_IP:/tmp/cv-output/camera-viewer-app.tar.gz"
ok "File copiati sul NUC"

# ── Step 4: Build immagine sul NUC ────────────────────────────────────────────
step 4 "Build immagine sul NUC ($NUC_IP) — grub nativo, ~20 min..."
echo ""
echo -e "  ${C}Il NUC usa losetup e grub-mkstandalone nativi — nessun problema!${E}"
echo "  Log in tempo reale:"
echo ""

sshpass -p "$NUC_PASS" ssh "${SSH_OPTS[@]}" "$NUC_USER@$NUC_IP" \
    "sudo bash /tmp/cv-build/build_image_inside.sh '$VERSION' '/tmp/cv-output' '/tmp/cv-output/camera-viewer-app.tar.gz'"

# ── Step 5: Copia immagine sul Mac ────────────────────────────────────────────
step 5 "Copia immagine compressa sul Mac..."
mkdir -p "$OUTPUT_DIR"
sshpass -p "$NUC_PASS" scp "${SCP_OPTS[@]}" \
    "$NUC_USER@$NUC_IP:/tmp/cv-output/camera-viewer-v${VERSION}.img.xz" \
    "$OUTPUT_IMG"

# Pulizia temporanei
rm -f "$APP_TGZ"
sshpass -p "$NUC_PASS" ssh "${SSH_OPTS[@]}" "$NUC_USER@$NUC_IP" \
    "sudo rm -rf /tmp/cv-build /tmp/cv-output" 2>/dev/null || true

SIZE=$(ls -lh "$OUTPUT_IMG" | awk '{print $5}')
ok "Immagine: dist/camera-viewer-v${VERSION}.img.xz ($SIZE)"

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
