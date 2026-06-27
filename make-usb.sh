#!/bin/bash
# =============================================================================
# Camera Viewer — Crea USB Live
#
# Scrive l'immagine Camera Viewer su una USB.
# Il PC NON ha bisogno di hard disk — gira tutto dalla USB.
#
# Uso:
#   bash make-usb.sh [/dev/diskX] [camera-viewer-v2.6.img.xz]
#
# Requisiti: macOS, curl (solo per download automatico se non hai l'immagine)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_IMG="$SCRIPT_DIR/dist/camera-viewer-v2.6.img.xz"

# Colori
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

header() {
    clear
    echo -e "${CYAN}${BOLD}"
    echo "  ╔══════════════════════════════════════════════════╗"
    echo "  ║   🎥  Camera Viewer — Crea USB Live             ║"
    echo "  ║       di Enzo Pellegrino                        ║"
    echo "  ╚══════════════════════════════════════════════════╝"
    echo -e "${RESET}"
    echo "  Il PC NON ha bisogno di hard disk."
    echo "  Plug USB → F10 → Camera Viewer con tutta la potenza del PC."
    echo ""
}

ok()    { echo -e "  ${GREEN}✓${RESET} $1"; }
warn()  { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
err()   { echo -e "  ${RED}✗ ERRORE:${RESET} $1"; exit 1; }

header

# ── Trova l'immagine ──────────────────────────────────────────────────────────
IMG_FILE="${2:-$DEFAULT_IMG}"

if [ ! -f "$IMG_FILE" ]; then
    echo -e "  ${YELLOW}Immagine non trovata:${RESET} $IMG_FILE"
    echo ""
    echo "  Per creare l'immagine:"
    echo -e "    ${BOLD}bash make-image.sh${RESET}"
    echo ""
    exit 1
fi

IMG_SIZE=$(ls -lh "$IMG_FILE" | awk '{print $5}')
echo -e "  Immagine: ${BOLD}$(basename "$IMG_FILE")${RESET} ($IMG_SIZE)"
echo ""

# ── Seleziona USB ────────────────────────────────────────────────────────────
if [ -z "${1:-}" ] || [[ "${1:-}" == /dev/* ]] && [ -z "${2:-}" ]; then
    USB_DEV="${1:-}"
fi

if [ -z "${USB_DEV:-}" ]; then
    echo -e "  ${BOLD}Dischi esterni disponibili:${RESET}"
    diskutil list | grep -E "^\/(dev\/disk[0-9]+) \(external" | while read -r line; do
        DEV=$(echo "$line" | awk '{print $1}')
        SIZE=$(diskutil info "$DEV" 2>/dev/null | grep "Disk Size" | sed 's/.*: //' | sed 's/ (.*//')
        NAME=$(diskutil info "$DEV" 2>/dev/null | grep "Media Name" | sed 's/.*: //')
        echo "    $DEV  —  $SIZE  —  $NAME"
    done
    echo ""
    read -rp "  Inserisci il device USB (es. /dev/disk2): " USB_DEV
fi

# Verifica disco
DISK_INFO=$(diskutil info "$USB_DEV" 2>/dev/null) || err "$USB_DEV non trovato"
DISK_SIZE=$(echo "$DISK_INFO" | grep "Disk Size" | sed 's/.*Disk Size: //' | sed 's/ .*//')
DISK_NAME=$(echo "$DISK_INFO" | grep "Media Name" | sed 's/.*Media Name: //')
DISK_NUM="${USB_DEV#/dev/disk}"

# Verifica dimensione minima — immagine è 6GB, serve almeno 7GB
DISK_BYTES=$(diskutil info "$USB_DEV" | grep "Disk Size" | grep -o '[0-9]* Bytes' | awk '{print $1}')
MIN_BYTES=$((7 * 1024 * 1024 * 1024))
if [ -n "$DISK_BYTES" ] && [ "$DISK_BYTES" -lt "$MIN_BYTES" ]; then
    err "USB troppo piccola ($DISK_SIZE). Serve almeno 8GB (consigliato 16GB+)."
fi

echo ""
echo -e "  Disco: ${BOLD}$USB_DEV${RESET} — $DISK_SIZE — $DISK_NAME"
echo ""
echo -e "  ${RED}${BOLD}⚠  ATTENZIONE: tutti i dati su $USB_DEV saranno CANCELLATI!${RESET}"
read -rp "  Continuare? [y/N]: " CONFIRM
[[ "$CONFIRM" =~ ^[yY]$ ]] || { echo "  Annullato."; exit 0; }
echo ""

# ── Scrivi immagine ───────────────────────────────────────────────────────────
echo -e "  ${BOLD}Scrittura in corso — attendere...${RESET}"
echo "  (potrebbe richiedere 3-8 minuti a seconda della velocità USB)"
echo ""

diskutil unmountDisk "$USB_DEV" 2>/dev/null || true

# Decomprimi + scrivi in un'unica pipe (nessun file temporaneo)
sudo bash -c "xz -dc '$IMG_FILE' | dd of='/dev/rdisk${DISK_NUM}' bs=1m"
sudo sync

echo ""
ok "Immagine scritta sulla USB"

# ── Verifica ─────────────────────────────────────────────────────────────────
sleep 2
PARTS=$(diskutil list "$USB_DEV" 2>/dev/null | grep -c "EFI\|cv-system\|cv-data" || echo "0")
if [ "$PARTS" -gt 0 ]; then
    ok "Partizioni riconosciute ($PARTS trovate)"
fi

diskutil unmountDisk "$USB_DEV" 2>/dev/null || true

# ── Fine ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}${BOLD}║  ✅ USB pronta!                                  ║${RESET}"
echo -e "${GREEN}${BOLD}╠══════════════════════════════════════════════════╣${RESET}"
echo -e "${GREEN}${BOLD}║  1. Stacca USB dal Mac                            ║${RESET}"
echo -e "${GREEN}${BOLD}║  2. Inseriscila nel PC (non serve hard disk!)     ║${RESET}"
echo -e "${GREEN}${BOLD}║  3. Accendi → F10/F12/ESC → seleziona USB         ║${RESET}"
echo -e "${GREEN}${BOLD}║  4. Camera Viewer parte in ~30 secondi            ║${RESET}"
echo -e "${GREEN}${BOLD}║                                                   ║${RESET}"
echo -e "${GREEN}${BOLD}║  Dal browser: http://[IP mostrato sullo schermo]  ║${RESET}"
echo -e "${GREEN}${BOLD}║  Login: admin / admin  (cambia subito!)           ║${RESET}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════╝${RESET}"
echo ""
