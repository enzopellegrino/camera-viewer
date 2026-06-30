#!/bin/bash
# =============================================================================
# Camera Viewer — Installa sul disco interno
#
# Gira sul PC target già bootato dalla USB live.
# Trova il disco interno, partiziona, copia il sistema, installa GRUB e riavvia.
#
# Uso automatico: chiamato da cv-installer.service al primo boot dalla USB.
# Uso manuale:    sudo bash /opt/cv-install/install-to-disk.sh
# =============================================================================
set -euo pipefail

R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; C='\033[0;36m'; B='\033[1m'; E='\033[0m'
MNT=/mnt/cv-target
LOG=/tmp/cv-install.log
TOTAL=7

exec > >(tee -a "$LOG") 2>&1

hdr() {
    clear
    echo -e "${C}${B}"
    echo "  ╔══════════════════════════════════════════════════╗"
    echo "  ║   🎥  Camera Viewer — Installazione             ║"
    echo "  ║       Copia sistema su disco interno            ║"
    echo "  ╚══════════════════════════════════════════════════╝"
    echo -e "${E}"
}

ok()   { echo -e "  ${G}✓${E} $1"; }
err()  { echo -e "  ${R}✗ ERRORE:${E} $1"; echo "Vedi log: $LOG"; exit 1; }
step() { echo -e "\n${B}[$1/$TOTAL]${E} $2"; }
warn() { echo -e "  ${Y}⚠${E}  $1"; }

hdr

# ── Trova disco USB di boot (da escludere) ────────────────────────────────────
step 1 "Identificazione dischi..."

USB_DEV=$(findmnt -n -o SOURCE / 2>/dev/null | sed 's/p\?[0-9]*$//' | sed 's/[0-9]*$//')
[ -z "$USB_DEV" ] && err "Impossibile determinare il device di boot"
ok "Boot da: $USB_DEV"

# ── Trova disco interno ───────────────────────────────────────────────────────
INTERNAL=""
for DEV in $(lsblk -d -o NAME,TYPE | awk '$2=="disk"{print "/dev/"$1}'); do
    [ "$DEV" = "$USB_DEV" ] && continue
    # Escludi dispositivi troppo piccoli (<4GB)
    SIZE_BYTES=$(lsblk -b -d -o SIZE "$DEV" 2>/dev/null | tail -1 | tr -d ' ')
    [ "${SIZE_BYTES:-0}" -lt $((4 * 1024 * 1024 * 1024)) ] && continue
    INTERNAL="$DEV"
    break
done

if [ -z "$INTERNAL" ]; then
    echo ""
    echo "  Dischi disponibili:"
    lsblk -d -o NAME,SIZE,MODEL,TYPE | grep disk
    echo ""
    read -rp "  Device disco interno (es. /dev/sda o /dev/nvme0n1): " INTERNAL
fi

DISK_SIZE=$(lsblk -d -o SIZE "$INTERNAL" 2>/dev/null | tail -1 | tr -d ' ')
DISK_MODEL=$(lsblk -d -o MODEL "$INTERNAL" 2>/dev/null | tail -1 | tr -d ' ' || echo "")
ok "Disco interno: $INTERNAL — $DISK_SIZE ${DISK_MODEL:+($DISK_MODEL)}"

# Prefisso partizione (nvme usa p1, sata usa 1)
if [[ "$INTERNAL" == *nvme* ]]; then
    PART_EFI="${INTERNAL}p1"
    PART_SYS="${INTERNAL}p2"
    PART_DATA="${INTERNAL}p3"
else
    PART_EFI="${INTERNAL}1"
    PART_SYS="${INTERNAL}2"
    PART_DATA="${INTERNAL}3"
fi

# ── Conferma ─────────────────────────────────────────────────────────────────
echo ""
echo -e "  ${Y}${B}⚠  ATTENZIONE: $INTERNAL sarà completamente formattato!${E}"
echo -e "  ${Y}   Tutti i dati esistenti andranno persi.${E}"
echo ""

# In modalità automatica (chiamato dal servizio) procede senza chiedere
if [ "${CV_AUTO_INSTALL:-0}" = "1" ]; then
    echo "  Modalità automatica — installazione avviata..."
else
    read -rp "  Continuare? [y/N]: " CONFIRM
    [[ "$CONFIRM" =~ ^[yY]$ ]] || { echo "Annullato."; exit 0; }
fi

# ── Partizionamento ───────────────────────────────────────────────────────────
step 2 "Partizionamento $INTERNAL..."

# Smonta eventuali partizioni montate
umount "${INTERNAL}"* 2>/dev/null || true

parted -s "$INTERNAL" mklabel gpt
parted -s "$INTERNAL" mkpart EFI    fat32   1MiB    257MiB
parted -s "$INTERNAL" mkpart System ext4    257MiB  10497MiB
parted -s "$INTERNAL" mkpart Data   ext4    10497MiB 100%
parted -s "$INTERNAL" set 1 esp on

sleep 2
mkfs.vfat -F32 -n "CV-EFI"   "$PART_EFI" -I
mkfs.ext4 -L   "cv-system"   "$PART_SYS" -q -F
mkfs.ext4 -L   "cv-data"     "$PART_DATA" -q -F
ok "Disco partizionato"

# ── Copia sistema ─────────────────────────────────────────────────────────────
step 3 "Copia sistema USB → disco interno (~5-15 min)..."
echo "  (dipende dalla velocità del disco)"

mkdir -p $MNT
mount "$PART_SYS" $MNT
mkdir -p $MNT/boot/efi
mount "$PART_EFI" $MNT/boot/efi
mkdir -p $MNT/data

rsync -aAX --delete --info=progress2 \
    --exclude='/proc/*'     \
    --exclude='/sys/*'      \
    --exclude='/dev/*'      \
    --exclude='/run/*'      \
    --exclude='/tmp/*'      \
    --exclude='/mnt/*'      \
    --exclude='/media/*'    \
    --exclude='/data/*'     \
    --exclude='/swap.img'   \
    --exclude='/boot/efi/*' \
    --exclude='/etc/systemd/system/cv-installer.service' \
    --exclude='/etc/systemd/system/multi-user.target.wants/cv-installer.service' \
    / $MNT/ 2>/dev/null
ok "Sistema copiato"

# ── Configurazione ────────────────────────────────────────────────────────────
step 4 "Configurazione fstab e sistema..."

EFI_UUID=$(blkid -s UUID -o value "$PART_EFI")
SYS_UUID=$(blkid -s UUID -o value "$PART_SYS")

tee $MNT/etc/fstab > /dev/null << FSTAB
UUID=$SYS_UUID  /          ext4  defaults,noatime  0 1
UUID=$EFI_UUID  /boot/efi  vfat  defaults          0 2
LABEL=cv-data   /data      ext4  defaults,noatime  0 2
FSTAB

# Rimuovi il servizio installer dal sistema installato (non deve girare di nuovo)
rm -f "$MNT/etc/systemd/system/cv-installer.service"
rm -f "$MNT/etc/systemd/system/multi-user.target.wants/cv-installer.service"
rm -f "$MNT/opt/cv-install/install-to-disk.sh"

ok "Configurazione completata"

# ── GRUB ─────────────────────────────────────────────────────────────────────
step 5 "Installazione GRUB..."

for d in dev dev/pts proc sys run; do mount --bind "/$d" "$MNT/$d" 2>/dev/null || true; done

chroot $MNT bash -c "
grub-install --target=x86_64-efi \
    --efi-directory=/boot/efi \
    --boot-directory=/boot \
    --recheck 2>&1 | tail -3
update-grub 2>&1 | tail -5
" || warn "GRUB: alcuni avvisi sono normali"

for d in run sys proc dev/pts dev; do umount "$MNT/$d" 2>/dev/null || true; done
ok "GRUB installato"

# ── Smonta ───────────────────────────────────────────────────────────────────
step 6 "Smontaggio dischi..."
umount $MNT/boot/efi
umount $MNT
ok "Dischi smontati"

# ── Fine ─────────────────────────────────────────────────────────────────────
step 7 "Installazione completata!"
echo ""
echo -e "${G}${B}╔══════════════════════════════════════════════════╗${E}"
echo -e "${G}${B}║  ✅ Camera Viewer installato sul disco interno!  ║${E}"
echo -e "${G}${B}╠══════════════════════════════════════════════════╣${E}"
echo -e "${G}${B}║  Config pulita — pronta per nuovo cliente.       ║${E}"
echo -e "${G}${B}║                                                  ║${E}"
echo -e "${G}${B}║  1. Stacca la USB                                ║${E}"
echo -e "${G}${B}║  2. Riavvia il PC                                ║${E}"
echo -e "${G}${B}║  3. Camera Viewer parte in automatico            ║${E}"
echo -e "${G}${B}╚══════════════════════════════════════════════════╝${E}"
echo ""

if [ "${CV_AUTO_INSTALL:-0}" = "1" ]; then
    echo "  Riavvio in 10 secondi..."
    sleep 10
    reboot
fi
