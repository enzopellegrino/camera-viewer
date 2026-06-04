#!/bin/bash
# =============================================================================
# Camera Viewer — Crea immagine disco distribuibile
#
# Usa il NUC (sistema funzionante) come sorgente.
# Produce dist/camera-viewer-v2.0.img.xz da distribuire ai clienti.
#
# Workflow:
#   bash make-image.sh [IP_NUC]   → crea l'immagine
#   bash make-usb.sh /dev/diskX   → scrive su USB
#
# Prerequisiti: NUC acceso, USB non necessaria
# Tempo: ~15-20 min
# Output: dist/camera-viewer-v2.0.img.xz (~3-4GB)
# USB minima: 16GB
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="2.0"
OUTPUT_DIR="$SCRIPT_DIR/dist"
OUTPUT_IMG="$OUTPUT_DIR/camera-viewer-v${VERSION}.img.xz"

NUC_IP="${1:-}"
NUC_USER="pi"
NUC_PASS="N1computer@2019"

# Partizioni immagine
IMG_SIZE_MB=11264      # 11GB raw (sistema NUC ~8.3GB + margine)
EFI_SIZE_MB=256
SYSTEM_SIZE_MB=10240   # 10GB sistema
# Data: resto (~768MB nell'immagine, si espande su USB al primo avvio)

R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; C='\033[0;36m'; B='\033[1m'; E='\033[0m'

hdr() {
    clear
    echo -e "${C}${B}"
    echo "  ╔══════════════════════════════════════════════════╗"
    echo "  ║   🎥  Camera Viewer v${VERSION} — Image Builder     ║"
    echo "  ║       Creato da Enzo Pellegrino                 ║"
    echo "  ╚══════════════════════════════════════════════════╝"
    echo -e "${E}"
    echo "  Sorgente: NUC (sistema reale x86_64)"
    echo "  Output:   dist/camera-viewer-v${VERSION}.img.xz"
    echo ""
}

ok()   { echo -e "  ${G}✓${E} $1"; }
err()  { echo -e "  ${R}✗ ERRORE:${E} $1"; exit 1; }
step() { echo -e "\n${B}[$1/$TOTAL]${E} $2"; }
TOTAL=5

hdr

# ── Verifica output esistente ─────────────────────────────────────────────────
mkdir -p "$OUTPUT_DIR"
if [ -f "$OUTPUT_IMG" ]; then
    SIZE=$(ls -lh "$OUTPUT_IMG" | awk '{print $5}')
    echo -e "  ${Y}Immagine già esistente: $SIZE${E}"
    read -rp "  Ricostruire? [y/N]: " REBUILD
    [[ "$REBUILD" =~ ^[yY]$ ]] || { echo "Annullato."; exit 0; }
fi

# ── Trova NUC ─────────────────────────────────────────────────────────────────
if [ -z "$NUC_IP" ]; then
    NUC_IP=$(python3 -c "import socket; print(socket.gethostbyname('camera-viewer.local'))" 2>/dev/null || true)
    [ -z "$NUC_IP" ] && read -rp "  IP del NUC: " NUC_IP
fi

SSH_O=(-o StrictHostKeyChecking=no -o PasswordAuthentication=yes -o PubkeyAuthentication=no)
SCP_O=(-o StrictHostKeyChecking=no -o PasswordAuthentication=yes -o PubkeyAuthentication=no)

step 1 "Connessione al NUC ($NUC_IP)..."
HOSTNAME=$(sshpass -p "$NUC_PASS" ssh "${SSH_O[@]}" "$NUC_USER@$NUC_IP" "hostname" 2>/dev/null) \
    || err "NUC non raggiungibile su $NUC_IP"
NUC_USED=$(sshpass -p "$NUC_PASS" ssh "${SSH_O[@]}" "$NUC_USER@$NUC_IP" \
    "df -BM / | tail -1 | awk '{print \$3}'" 2>/dev/null)
ok "NUC: $HOSTNAME — sistema usato: $NUC_USED"

# ── Build immagine sul NUC ────────────────────────────────────────────────────
step 2 "Creazione immagine disco sul NUC (~10 min)..."
sshpass -p "$NUC_PASS" ssh "${SSH_O[@]}" "$NUC_USER@$NUC_IP" "sudo bash -s" << BUILDSSH
set -e
IMG=/tmp/camera-viewer-v${VERSION}.img
IMG_MB=${IMG_SIZE_MB}
EFI_MB=${EFI_SIZE_MB}
SYS_MB=${SYSTEM_SIZE_MB}

echo "Creazione immagine raw \${IMG_MB}MB..."
dd if=/dev/zero of=\$IMG bs=1M count=\$IMG_MB status=progress

echo "Partizionamento..."
parted -s \$IMG mklabel gpt
parted -s \$IMG mkpart EFI    fat32 1MiB \${EFI_MB}MiB
parted -s \$IMG mkpart System ext4  \${EFI_MB}MiB \$((EFI_MB+SYS_MB))MiB
parted -s \$IMG mkpart Data   ext4  \$((EFI_MB+SYS_MB))MiB 100%
parted -s \$IMG set 1 esp on

echo "Formattazione..."
LOOP=\$(losetup -f --show -P \$IMG)
echo "Loop: \$LOOP"
mkfs.vfat -F32 -n "CV-EFI"    \${LOOP}p1
mkfs.ext4 -L  "cv-system"     \${LOOP}p2 -q
mkfs.ext4 -L  "cv-data"       \${LOOP}p3 -q

MNT=/tmp/cv-img-mnt
mkdir -p \$MNT && mount \${LOOP}p2 \$MNT
mkdir -p \$MNT/boot/efi && mount \${LOOP}p1 \$MNT/boot/efi
mkdir -p \$MNT/data

echo "Copia sistema NUC nell immagine (rsync)..."
rsync -aAX --delete --info=progress2 \
    --exclude='/proc/*' --exclude='/sys/*' --exclude='/dev/*' \
    --exclude='/run/*'  --exclude='/tmp/*' --exclude='/mnt/*' \
    --exclude='/media/*' --exclude='/data/*' --exclude='/swap.img' \
    --exclude='/boot/efi/*' \
    --exclude='/home/pi/.config/camera-viewer/*' \
    --exclude='/home/pi/setup-nuc.*' \
    --exclude='/etc/NetworkManager/system-connections/*' \
    / \$MNT/ 2>/dev/null

echo "Aggiorno fstab..."
EFI_UUID=\$(blkid -s UUID -o value \${LOOP}p1)
SYS_UUID=\$(blkid -s UUID -o value \${LOOP}p2)
tee \$MNT/etc/fstab > /dev/null << EOF
UUID=\$SYS_UUID  /          ext4  defaults,noatime  0 1
UUID=\$EFI_UUID  /boot/efi  vfat  defaults          0 2
LABEL=cv-data   /data      ext4  defaults,noatime  0 2
EOF

echo "Config iniziale pulita (nessuna telecamera/VPN)..."
mkdir -p \$MNT/data/camera-viewer
cat > \$MNT/data/camera-viewer/config.json << 'CFGJSON'
{"cameras":[],"screens":[],"settings":{"kiosk_mode":true,"reconnect_delay_ms":5000,"render_fps":25},"site_name":"Camera Viewer","users":[]}
CFGJSON

echo "Installo GRUB dal chroot..."
for d in dev dev/pts proc sys run; do mount --bind /\$d \$MNT/\$d 2>/dev/null || true; done
chroot \$MNT bash -c "
grub-install --target=x86_64-efi --efi-directory=/boot/efi --boot-directory=/boot --removable --recheck 2>&1 | tail -2
update-grub 2>&1 | grep -E 'Found|done|error' | head -5
echo GRUB_OK
"
for d in run sys proc dev/pts dev; do umount \$MNT/\$d 2>/dev/null || true; done

# SOSTITUISCI BOOTX64.EFI con grub-mkimage (incorpora ricerca partizione)
# grub-install da solo non sa trovare la partizione su macchine diverse
KERNEL_VER=\$(ls \$MNT/boot/vmlinuz-*-generic 2>/dev/null | sort -V | tail -1 | sed 's|'\$MNT'/boot/vmlinuz-||')
cat > /tmp/grub-early-img.cfg << EARLY
search --no-floppy --label --set=root cv-system
set prefix=(\\\$root)/boot/grub
EARLY
grub-mkimage \
    --format=x86_64-efi \
    --output=\$MNT/boot/efi/EFI/BOOT/BOOTX64.EFI \
    --config=/tmp/grub-early-img.cfg \
    --prefix=/boot/grub \
    part_gpt fat ext2 normal boot linux search search_label all_video && \
echo "BOOTX64.EFI autocontenuto creato"

umount \$MNT/boot/efi && umount \$MNT
losetup -d \$LOOP

echo "Build completato: \$IMG"
BUILDSSH
ok "Immagine creata sul NUC"

# ── Comprimi ──────────────────────────────────────────────────────────────────
step 3 "Compressione immagine sul NUC (xz -6, ~5 min)..."
sshpass -p "$NUC_PASS" ssh "${SSH_O[@]}" "$NUC_USER@$NUC_IP" \
    "xz -6 -T0 /tmp/camera-viewer-v${VERSION}.img && echo Compresso"
ok "Compressione completata"

# ── Trasferimento sul Mac ─────────────────────────────────────────────────────
step 4 "Trasferimento immagine sul Mac..."
NUC_SIZE=$(sshpass -p "$NUC_PASS" ssh "${SSH_O[@]}" "$NUC_USER@$NUC_IP" \
    "ls -lh /tmp/camera-viewer-v${VERSION}.img.xz | awk '{print \$5}'" 2>/dev/null)
echo "  Dimensione: $NUC_SIZE — trasferimento in corso..."

sshpass -p "$NUC_PASS" scp "${SCP_O[@]}" \
    "$NUC_USER@$NUC_IP:/tmp/camera-viewer-v${VERSION}.img.xz" \
    "$OUTPUT_IMG"

# Pulizia NUC
sshpass -p "$NUC_PASS" ssh "${SSH_O[@]}" "$NUC_USER@$NUC_IP" \
    "rm -f /tmp/camera-viewer-v${VERSION}.img.xz" 2>/dev/null || true
ok "Immagine ricevuta sul Mac"

# ── Riepilogo ─────────────────────────────────────────────────────────────────
step 5 "Completato!"
SIZE=$(ls -lh "$OUTPUT_IMG" | awk '{print $5}')
echo ""
echo -e "${G}${B}╔══════════════════════════════════════════════════╗${E}"
echo -e "${G}${B}║  ✅ Immagine pronta per distribuzione!           ║${E}"
echo -e "${G}${B}╠══════════════════════════════════════════════════╣${E}"
echo -e "${G}${B}║  File:  dist/camera-viewer-v${VERSION}.img.xz       ║${E}"
echo -e "${G}${B}║  Size:  $SIZE                                    ║${E}"
echo -e "${G}${B}║  USB:   minimo 16GB (raccomandato 32GB)          ║${E}"
echo -e "${G}${B}║                                                  ║${E}"
echo -e "${G}${B}║  Per creare una USB:                             ║${E}"
echo -e "${G}${B}║    bash make-usb.sh /dev/diskX                   ║${E}"
echo -e "${G}${B}╚══════════════════════════════════════════════════╝${E}"
