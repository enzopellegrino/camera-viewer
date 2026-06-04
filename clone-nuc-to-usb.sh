#!/bin/bash
# =============================================================================
# Camera Viewer — Clona NUC funzionante su USB
#
# Copia il sistema NUC (già configurato e funzionante) sulla USB.
# Molto più affidabile di un build da zero.
#
# Uso: bash clone-nuc-to-usb.sh [IP_NUC]
# =============================================================================
set -euo pipefail

NUC_IP="${1:-}"
NUC_USER="pi"
NUC_PASS="N1computer@2019"

R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; C='\033[0;36m'; B='\033[1m'; E='\033[0m'

hdr() {
    clear
    echo -e "${C}${B}"
    echo "  ╔══════════════════════════════════════════════════╗"
    echo "  ║   🎥  Camera Viewer — Clone NUC → USB           ║"
    echo "  ║       Creato da Enzo Pellegrino                 ║"
    echo "  ╚══════════════════════════════════════════════════╝"
    echo -e "${E}"
}

ok()   { echo -e "  ${G}✓${E} $1"; }
err()  { echo -e "  ${R}✗ ERRORE:${E} $1"; exit 1; }
step() { echo -e "\n${B}[$1/$TOTAL]${E} $2"; }
TOTAL=6

hdr

# ── Trova NUC ────────────────────────────────────────────────────────────────
if [ -z "$NUC_IP" ]; then
    NUC_IP=$(python3 -c "import socket; print(socket.gethostbyname('camera-viewer.local'))" 2>/dev/null || true)
    [ -z "$NUC_IP" ] && read -rp "  IP del NUC: " NUC_IP
fi

SSH_O=(-o StrictHostKeyChecking=no -o PasswordAuthentication=yes -o PubkeyAuthentication=no)
SCP_O=(-o StrictHostKeyChecking=no -o PasswordAuthentication=yes -o PubkeyAuthentication=no)

step 1 "Connessione al NUC ($NUC_IP)..."
HOSTNAME=$(sshpass -p "$NUC_PASS" ssh "${SSH_O[@]}" "$NUC_USER@$NUC_IP" "hostname" 2>/dev/null) \
    || err "NUC non raggiungibile"
ok "NUC: $HOSTNAME"

# ── Trova USB sul NUC ────────────────────────────────────────────────────────
step 2 "Inserisci la USB nel NUC, poi premi Invio..."
read -rp "   USB inserita? [Invio]: "

USB_DEV=$(sshpass -p "$NUC_PASS" ssh "${SSH_O[@]}" "$NUC_USER@$NUC_IP" \
    "lsblk -o NAME,SIZE,LABEL,TYPE -d | grep -i disk | grep -v sda | awk '{print \"/dev/\"\$1}' | head -1" 2>/dev/null)

if [ -z "$USB_DEV" ]; then
    echo "  USB non rilevata automaticamente."
    sshpass -p "$NUC_PASS" ssh "${SSH_O[@]}" "$NUC_USER@$NUC_IP" \
        "lsblk -o NAME,SIZE,TYPE -d | grep disk"
    read -rp "  Device USB sul NUC (es. /dev/sdb): " USB_DEV
fi
ok "USB: $USB_DEV"

echo ""
echo -e "  ${Y}⚠  ATTENZIONE: tutti i dati su $USB_DEV saranno cancellati!${E}"
read -rp "  Continuare? [y/N]: " CONFIRM
[[ "$CONFIRM" =~ ^[yY]$ ]] || { echo "Annullato."; exit 0; }

# ── Partiziona e formatta USB ────────────────────────────────────────────────
step 3 "Partizionamento USB sul NUC..."
sshpass -p "$NUC_PASS" ssh "${SSH_O[@]}" "$NUC_USER@$NUC_IP" "sudo bash -s '$USB_DEV'" << 'PARTSCRIPT'
USB="$1"
# Formatta con 3 partizioni
sudo parted -s "$USB" mklabel gpt
sudo parted -s "$USB" mkpart EFI    fat32  1MiB   257MiB
sudo parted -s "$USB" mkpart System ext4   257MiB 10497MiB
sudo parted -s "$USB" mkpart Data   ext4   10497MiB 100%
sudo parted -s "$USB" set 1 esp on
sleep 2
sudo mkfs.vfat -F32 -n "CV-EFI"    "${USB}1"
sudo mkfs.ext4 -L  "cv-system"     "${USB}2" -q
sudo mkfs.ext4 -L  "cv-data"       "${USB}3" -q
echo "Partizionamento completato"
PARTSCRIPT
ok "USB partizionata"

# ── Clona sistema NUC → USB ──────────────────────────────────────────────────
step 4 "Clonazione sistema NUC → USB (~10-15 min)..."
echo "  (rsync di tutto il filesystem, esclusi dati cliente e /home)"

sshpass -p "$NUC_PASS" ssh "${SSH_O[@]}" "$NUC_USER@$NUC_IP" "sudo bash -s '$USB_DEV'" << 'CLONESCRIPT'
USB="$1"
MNT=/mnt/cv-clone

sudo mkdir -p $MNT
sudo mount "${USB}2" $MNT
sudo mkdir -p $MNT/boot/efi
sudo mount "${USB}1" $MNT/boot/efi

echo "Rsync sistema..."
sudo rsync -aAX --delete --info=progress2 \
    --exclude='/proc/*'    \
    --exclude='/sys/*'     \
    --exclude='/dev/*'     \
    --exclude='/run/*'     \
    --exclude='/tmp/*'     \
    --exclude='/mnt/*'     \
    --exclude='/media/*'   \
    --exclude='/data/*'    \
    --exclude='/swap.img'  \
    --exclude='/boot/efi/*' \
    --exclude='/home/pi/.config/camera-viewer/*' \
    --exclude='/home/pi/setup-nuc.*' \
    --exclude='/etc/NetworkManager/system-connections/*' \
    / $MNT/ 2>/dev/null
echo "Rsync completato"
CLONESCRIPT
ok "Sistema clonato"

# ── Aggiorna fstab e GRUB ────────────────────────────────────────────────────
step 5 "Aggiornamento fstab e GRUB per USB..."
sshpass -p "$NUC_PASS" ssh "${SSH_O[@]}" "$NUC_USER@$NUC_IP" "sudo bash -s '$USB_DEV'" << 'GRUBSCRIPT'
USB="$1"
MNT=/mnt/cv-clone

# UUID delle partizioni USB
EFI_UUID=$(sudo blkid -s UUID -o value "${USB}1")
SYS_UUID=$(sudo blkid -s UUID -o value "${USB}2")
echo "EFI: $EFI_UUID / Sys: $SYS_UUID"

# fstab aggiornato per USB
sudo tee $MNT/etc/fstab > /dev/null << FSTAB
UUID=$SYS_UUID  /          ext4  defaults,noatime  0 1
UUID=$EFI_UUID  /boot/efi  vfat  defaults          0 2
LABEL=cv-data   /data      ext4  defaults,noatime  0 2
FSTAB

# Config iniziale pulita (senza telecamere/VPN del NUC)
sudo mkdir -p $MNT/data/camera-viewer
sudo tee $MNT/data/camera-viewer/config.json > /dev/null << 'CFGJSON'
{"cameras":[],"screens":[],"settings":{"kiosk_mode":true,"reconnect_delay_ms":5000,"render_fps":25},"site_name":"Camera Viewer","users":[]}
CFGJSON

# GRUB dal chroot (il modo corretto Ubuntu)
for d in dev dev/pts proc sys run; do sudo mount --bind /$d $MNT/$d 2>/dev/null || true; done

sudo chroot $MNT bash -c "
grub-install --target=x86_64-efi \
    --efi-directory=/boot/efi \
    --boot-directory=/boot \
    --removable --recheck 2>&1
update-grub 2>&1 | tail -5
echo GRUB_OK
"

for d in run sys proc dev/pts dev; do sudo umount $MNT/$d 2>/dev/null || true; done
sudo umount $MNT/boot/efi
sudo umount $MNT
echo "GRUB e fstab aggiornati"
GRUBSCRIPT
ok "fstab e GRUB aggiornati"

# ── Fine ─────────────────────────────────────────────────────────────────────
step 6 "Completato!"
echo ""
echo -e "${G}${B}╔══════════════════════════════════════════════════╗${E}"
echo -e "${G}${B}║  ✅ USB clonata dal NUC!                         ║${E}"
echo -e "${G}${B}╠══════════════════════════════════════════════════╣${E}"
echo -e "${G}${B}║  Il sistema USB è identico al NUC funzionante.   ║${E}"
echo -e "${G}${B}║  Config pulita — pronta per nuovo cliente.       ║${E}"
echo -e "${G}${B}║                                                  ║${E}"
echo -e "${G}${B}║  Stacca USB dal NUC → inserisci nel PC → F10    ║${E}"
echo -e "${G}${B}╚══════════════════════════════════════════════════╝${E}"
