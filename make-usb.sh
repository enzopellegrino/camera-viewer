#!/bin/bash
# =============================================================================
# Camera Viewer — USB Installer Creator
#
# Crea una USB di installazione universale per qualsiasi PC/NUC x86_64.
# L'installer è completamente autonomo: non richiede internet durante
# l'installazione OS. Solo i pacchetti apt vengono scaricati al primo avvio.
#
# Uso:
#   bash make-usb.sh [/dev/diskX]
#
# Requisiti: macOS con Homebrew opzionale, Python 3, curl, diskutil
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ISO_URL="https://releases.ubuntu.com/24.04.2/ubuntu-24.04.2-live-server-amd64.iso"
ISO_CACHE="$HOME/Downloads/ubuntu-24.04.2-live-server-amd64.iso"
WORK_DIR="$(mktemp -d)"
ORIG_GRUB_STR="set timeout=30"
GRUB_ORIG_SIZE=573

# Colori
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

# Pulizia work dir all'uscita
trap "rm -rf '$WORK_DIR'" EXIT

header() {
    echo ""
    echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════╗${RESET}"
    echo -e "${CYAN}${BOLD}║   🎥  Camera Viewer — USB Installer Creator      ║${RESET}"
    echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════╝${RESET}"
    echo ""
}

step() { echo -e "${BOLD}[$1/$TOTAL_STEPS]${RESET} $2"; }
ok()   { echo -e "     ${GREEN}✓${RESET} $1"; }
warn() { echo -e "     ${YELLOW}⚠${RESET}  $1"; }
err()  { echo -e "${RED}ERRORE:${RESET} $1"; exit 1; }

TOTAL_STEPS=6

# ── Header ───────────────────────────────────────────────────────────────────
header

# ── Selezione USB ────────────────────────────────────────────────────────────
if [ -z "${1:-}" ]; then
    echo -e "${BOLD}Dischi esterni disponibili:${RESET}"
    diskutil list | grep -A3 "(external" | grep "^/dev/disk" || true
    echo ""
    read -rp "Inserisci il device USB (es. /dev/disk2): " USB_DEV
else
    USB_DEV="$1"
fi

# Verifica che sia un disco esterno
DISK_INFO=$(diskutil info "$USB_DEV" 2>/dev/null) || err "$USB_DEV non trovato"
if ! echo "$DISK_INFO" | grep -qiE "removable|external|yes"; then
    warn "$USB_DEV potrebbe non essere un disco rimovibile."
fi

DISK_SIZE=$(echo "$DISK_INFO" | grep "Disk Size" | sed 's/.*Disk Size: //' | sed 's/ .*//')
DISK_NAME=$(echo "$DISK_INFO" | grep "Media Name" | sed 's/.*Media Name: //')
DISK_NUM="${USB_DEV#/dev/disk}"

echo ""
echo -e "  Disco: ${BOLD}$USB_DEV${RESET} — $DISK_SIZE"
echo -e "  Nome:  $DISK_NAME"
echo ""
echo -e "${RED}${BOLD}⚠  ATTENZIONE: tutti i dati su $USB_DEV saranno CANCELLATI!${RESET}"
read -rp "Continuare? [y/N]: " CONFIRM
[[ "$CONFIRM" =~ ^[yY]$ ]] || { echo "Annullato."; exit 0; }

# ── Step 1: ISO Ubuntu ───────────────────────────────────────────────────────
echo ""
step 1 "ISO Ubuntu Server 24.04..."
ISO_SIZE=$(stat -f%z "$ISO_CACHE" 2>/dev/null || echo 0)
if [ "$ISO_SIZE" -gt 2900000000 ]; then
    ok "Già in cache ($ISO_CACHE)"
else
    echo "     Download in corso (~2.7 GB)..."
    curl -L -C - -o "$ISO_CACHE" "$ISO_URL" --progress-bar
    ok "ISO scaricata"
fi

# ── Step 2: Archivio app ─────────────────────────────────────────────────────
echo ""
step 2 "Creazione archivio app..."
cd "$SCRIPT_DIR"
tar czf "$WORK_DIR/camera-viewer.tar.gz" \
    --exclude='.git' --exclude='.venv' --exclude='dist' --exclude='build' \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='*.spec' \
    --exclude='make-usb.sh' .
APP_SIZE=$(ls -lh "$WORK_DIR/camera-viewer.tar.gz" | awk '{print $5}')
ok "Archivio creato ($APP_SIZE)"

# ── Step 3: Genera user-data con app embedded ────────────────────────────────
echo ""
step 3 "Generazione user-data (app embedded in base64)..."
python3 "$SCRIPT_DIR/setup/generate_user_data.py" \
    "$WORK_DIR/camera-viewer.tar.gz" \
    "$SCRIPT_DIR/setup/setup_nuc.sh" \
    > "$WORK_DIR/user-data"
: > "$WORK_DIR/meta-data"
UD_SIZE=$(wc -c < "$WORK_DIR/user-data")
ok "user-data generato (${UD_SIZE} byte)"

# ── Step 4: Flash ISO ────────────────────────────────────────────────────────
echo ""
step 4 "Flash ISO sulla USB (richiede sudo)..."
diskutil unmountDisk "$USB_DEV" 2>/dev/null || true
echo "     dd in corso — attendere ~1 min..."
sudo dd if="$ISO_CACHE" of="/dev/rdisk${DISK_NUM}" bs=1m 2>&1 | \
    grep -v "^$" || true
sudo sync
ok "Flash completato"

# ── Step 5: Patch EFI/CIDATA ─────────────────────────────────────────────────
echo ""
step 5 "Patch partizione EFI → CIDATA (user-data + app)..."
EFI_IMG="$WORK_DIR/efi.img"
EFI_MNT="$WORK_DIR/efi-mnt"

sudo dd if="/dev/rdisk${DISK_NUM}s2" of="$EFI_IMG" bs=512 2>/dev/null
mkdir -p "$EFI_MNT"
hdiutil attach -nobrowse -mountpoint "$EFI_MNT" "$EFI_IMG"

diskutil rename "$EFI_MNT" CIDATA 2>/dev/null && ok "Label → CIDATA" || warn "Rename fallito (non blocca)"
cp "$WORK_DIR/user-data" "$EFI_MNT/user-data"
cp "$WORK_DIR/meta-data" "$EFI_MNT/meta-data"
ok "File copiati sulla partizione CIDATA"

sync
hdiutil detach "$EFI_MNT" 2>/dev/null || diskutil unmount "$EFI_MNT" 2>/dev/null || true

sudo dd if="$EFI_IMG" of="/dev/rdisk${DISK_NUM}s2" bs=512 2>/dev/null
sudo sync
ok "Partizione CIDATA scritta sull'USB"

# ── Step 6: Patch GRUB (aggiunge 'autoinstall') ──────────────────────────────
echo ""
step 6 "Patch grub.cfg — schermata boot Camera Viewer..."
python3 - << 'PYEOF' > "$WORK_DIR/grub-new.cfg"
import sys

# ── GRUB branded per Camera Viewer ──────────────────────────────────────
# Colori: sfondo nero, testo ciano (tema professionale scuro)
# Voci menu: italiano, branding Camera Viewer
# Timeout: 8s poi avvia automaticamente l'installazione
# Limite: esattamente 573 byte (overwrite in-place del grub.cfg ISO)
content = (
    'set timeout=8\n'
    'set default=0\n'
    '\n'
    'set color_normal=cyan/black\n'
    'set color_highlight=black/cyan\n'
    'set menu_color_normal=white/black\n'
    'set menu_color_highlight=black/cyan\n'
    '\n'
    'menuentry " Installa Camera Viewer v2.0" {\n'
    '\tset gfxpayload=keep\n'
    '\tlinux\t/casper/vmlinuz autoinstall  ---\n'
    '\tinitrd\t/casper/initrd\n'
    '}\n'
    'menuentry " Installa manualmente" {\n'
    '\tset gfxpayload=keep\n'
    '\tlinux\t/casper/vmlinuz  ---\n'
    '\tinitrd\t/casper/initrd\n'
    '}\n'
    'if [ "$grub_platform" = "efi" ]; then\n'
    'menuentry \'UEFI Firmware Settings\' {\n'
    '\tfwsetup\n'
    '}\n'
    'fi\n'
)
orig = 573
size = len(content.encode())
if size > orig:
    sys.stderr.write(f'ERRORE: grub.cfg troppo grande ({size} > {orig})\n')
    sys.exit(1)
sys.stderr.write(f'grub.cfg: {size}/{orig} byte\n')
sys.stdout.buffer.write((content + ' ' * (orig - size)).encode())
PYEOF

# Trova offset grub.cfg nel raw device
OFFSET=$(sudo grep -boa "$ORIG_GRUB_STR" "/dev/rdisk${DISK_NUM}s1" 2>/dev/null | head -1 | cut -d: -f1)
if [ -z "$OFFSET" ]; then
    warn "Offset grub.cfg non trovato — skip patch (l'utente dovrà premere 'e' al boot GRUB)"
else
    sudo dd if="$WORK_DIR/grub-new.cfg" of="/dev/disk${DISK_NUM}s1" \
        bs=1 seek="$OFFSET" conv=notrunc 2>/dev/null
    ok "grub.cfg patchato (offset $OFFSET)"
fi

# Smonta
sudo sync
diskutil unmountDisk "$USB_DEV" 2>/dev/null || true

# ── Riepilogo ────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}${BOLD}║  ✅ USB pronta!                                  ║${RESET}"
echo -e "${GREEN}${BOLD}╠══════════════════════════════════════════════════╣${RESET}"
echo -e "${GREEN}${BOLD}║  1. Stacca USB dal Mac                            ║${RESET}"
echo -e "${GREEN}${BOLD}║  2. Inseriscila nel PC/NUC                        ║${RESET}"
echo -e "${GREEN}${BOLD}║  3. Accendi → F10/F12/ESC → seleziona USB         ║${RESET}"
echo -e "${GREEN}${BOLD}║  4. Installazione automatica (~10 min)             ║${RESET}"
echo -e "${GREEN}${BOLD}║  5. Al riavvio: setup + apertura portale web      ║${RESET}"
echo -e "${GREEN}${BOLD}║                                                   ║${RESET}"
echo -e "${GREEN}${BOLD}║  Login portale: admin / admin                     ║${RESET}"
echo -e "${GREEN}${BOLD}║  ⚠  Cambia subito la password!                    ║${RESET}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════╝${RESET}"
echo ""
