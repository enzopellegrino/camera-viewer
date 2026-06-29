#!/bin/bash
# =============================================================================
# Camera Viewer v2.7 — Installer
#
# Viene avviato automaticamente quando si boota la USB con cv_install=1
# (voce "Installa" nel menu GRUB).
#
# Copia il sistema live dalla USB al disco interno del PC.
# =============================================================================
set -euo pipefail

R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'
C='\033[0;36m'; B='\033[1m'; E='\033[0m'

# ── Cleanup on error: smonta tutto per non lasciare il disco in stato inconsistente
MNT=/tmp/cv-install-mnt
_cleanup() {
    local EXIT=$?
    [ $EXIT -eq 0 ] && return
    echo -e "\n  ${R}${B}Errore durante l'installazione — smontaggio dischi...${E}"
    umount "$MNT/sys/firmware/efi/efivars" 2>/dev/null || true
    for d in run sys proc dev/pts dev boot/efi data; do
        umount "$MNT/$d" 2>/dev/null || true
    done
    umount "$MNT" 2>/dev/null || true
    echo -e "  ${R}Installazione interrotta. Il disco potrebbe essere inutilizzabile.${E}"
    echo -e "  Riavvia dalla USB e riprova."
}
trap '_cleanup' ERR

clear
echo -e "${C}${B}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║   🎥  Camera Viewer — Installer                 ║"
echo "  ║       Installazione su disco interno            ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${E}"
echo ""
echo "  Questo script installa Camera Viewer sul disco interno del PC."
echo -e "  ${R}Il disco scelto verrà formattato. Tutti i dati esistenti saranno cancellati.${E}"
echo ""

# ── Rileva disco sorgente (USB da cui stiamo bootando) ────────────────────────
# In live-boot, / è overlayfs: findmnt restituisce "overlay", non una partizione.
# Cerchiamo il medium live nei mount point noti di live-boot.
ROOT_DEV=$(findmnt -n -o SOURCE / | sed 's/\[.*//')
ROOT_DISK=$(lsblk -no PKNAME "$ROOT_DEV" 2>/dev/null || echo "")
if [[ -z "$ROOT_DISK" ]]; then
    for MNTPT in /run/live/medium /usr/lib/live/mount/medium; do
        LIVE_DEV=$(findmnt -n -o SOURCE "$MNTPT" 2>/dev/null || true)
        if [[ -n "$LIVE_DEV" ]]; then
            ROOT_DISK=$(lsblk -no PKNAME "$LIVE_DEV" 2>/dev/null || echo "")
            [[ -n "$ROOT_DISK" ]] && break
        fi
    done
fi
echo -e "  Sistema sorgente (USB): ${B}/dev/${ROOT_DISK:-sconosciuto}${E}"
echo ""

# ── Lista dischi interni disponibili ──────────────────────────────────────────
echo -e "  ${B}Dischi interni disponibili:${E}"
echo ""

DISKS=()
IDX=0
while IFS= read -r line; do
    DEV=$(echo "$line" | awk '{print $1}')
    DISK_NAME=$(basename "$DEV")
    [[ "$DISK_NAME" == "$ROOT_DISK" ]] && continue
    [[ "$DEV" == *loop* ]] && continue
    [[ "$DEV" == *sr* ]] && continue
    # Exclude USB transport disks (extra safety net if ROOT_DISK detection failed)
    TRAN=$(lsblk -dno TRAN "$DEV" 2>/dev/null || echo "")
    [[ "$TRAN" == "usb" ]] && continue
    SIZE=$(echo "$line" | awk '{print $2}')
    MODEL=$(echo "$line" | awk '{$1=$2=""; print}' | xargs)
    echo -e "    ${B}[$IDX]${E} $DEV — $SIZE — $MODEL"
    DISKS+=("$DEV")
    IDX=$((IDX+1))
done < <(lsblk -dpno NAME,SIZE,MODEL)

echo ""

if [ ${#DISKS[@]} -eq 0 ]; then
    echo -e "  ${R}Nessun disco interno trovato.${E}"
    echo "  Verifica che il PC abbia un disco interno collegato."
    echo ""
    read -rp "  Premi INVIO per uscire..." _
    exit 1
fi

# ── Seleziona disco target ─────────────────────────────────────────────────────
if [ ${#DISKS[@]} -eq 1 ]; then
    TARGET="${DISKS[0]}"
    DISK_SIZE=$(lsblk -dno SIZE "$TARGET")
    DISK_MODEL=$(lsblk -dno MODEL "$TARGET" | xargs)
    echo -e "  Disco selezionato automaticamente: ${B}$TARGET${E} — $DISK_SIZE — $DISK_MODEL"
else
    read -rp "  Scegli il disco [0-$((${#DISKS[@]}-1))]: " CHOICE
    if ! [[ "$CHOICE" =~ ^[0-9]+$ ]] || [ "$CHOICE" -ge "${#DISKS[@]}" ]; then
        echo -e "  ${R}Scelta non valida.${E}"
        exit 1
    fi
    TARGET="${DISKS[$CHOICE]}"
    DISK_SIZE=$(lsblk -dno SIZE "$TARGET")
    DISK_MODEL=$(lsblk -dno MODEL "$TARGET" | xargs)
fi

# ── Controllo dimensione minima (16GB) ────────────────────────────────────────
DISK_BYTES=$(lsblk -dno SIZE --bytes "$TARGET")
MIN_BYTES=$((16 * 1024 * 1024 * 1024))
if [ "$DISK_BYTES" -lt "$MIN_BYTES" ]; then
    echo -e "  ${R}Disco troppo piccolo ($DISK_SIZE). Serve almeno 16GB.${E}"
    exit 1
fi

echo ""
echo -e "  ${R}${B}╔══════════════════════════════════════════════════╗${E}"
echo -e "  ${R}${B}║  ⚠  ATTENZIONE — OPERAZIONE IRREVERSIBILE        ║${E}"
echo -e "  ${R}${B}╠══════════════════════════════════════════════════╣${E}"
echo -e "  ${R}${B}║  Disco: $TARGET — $DISK_SIZE${E}$(printf '%*s' $((38 - ${#TARGET} - ${#DISK_SIZE})) "")${R}${B}║${E}"
echo -e "  ${R}${B}║  Tutti i dati sul disco saranno CANCELLATI!      ║${E}"
echo -e "  ${R}${B}╚══════════════════════════════════════════════════╝${E}"
echo ""
echo -e "  Per confermare, digita esattamente: ${B}INSTALLA${E}"
read -rp "  > " CONFIRM

if [ "$CONFIRM" != "INSTALLA" ]; then
    echo ""
    echo "  Installazione annullata."
    exit 0
fi

echo ""
echo -e "  ${B}Avvio installazione — non spegnere il PC!${E}"
echo ""

# ── Partizionamento ────────────────────────────────────────────────────────────
echo "  [1/6] Partizionamento $TARGET..."
wipefs -af "$TARGET" >/dev/null 2>&1 || true
parted -s "$TARGET" mklabel gpt
parted -s "$TARGET" mkpart EFI    fat32  1MiB    257MiB
parted -s "$TARGET" mkpart System ext4   257MiB  10497MiB
parted -s "$TARGET" mkpart Data   ext4   10497MiB 100%
parted -s "$TARGET" set 1 esp on
partprobe "$TARGET" 2>/dev/null || true
sleep 3

# Nomi partizioni: /dev/sda1 oppure /dev/nvme0n1p1
if [[ "$TARGET" == *nvme* ]] || [[ "$TARGET" == *mmcblk* ]]; then
    P1="${TARGET}p1"; P2="${TARGET}p2"; P3="${TARGET}p3"
else
    P1="${TARGET}1"; P2="${TARGET}2"; P3="${TARGET}3"
fi

# ── Formattazione ──────────────────────────────────────────────────────────────
echo "  [2/6] Formattazione partizioni..."
mkfs.vfat -F32 -n "CV-EFI"   "$P1" >/dev/null
mkfs.ext4 -L   "cv-system"   "$P2" -q -F
mkfs.ext4 -L   "cv-data"     "$P3" -q -F

EFI_UUID=$(blkid -s UUID -o value "$P1")
SYS_UUID=$(blkid -s UUID -o value "$P2")

# ── Mount ──────────────────────────────────────────────────────────────────────
echo "  [3/6] Montaggio..."
mkdir -p "$MNT"
mount "$P2" "$MNT"
mkdir -p "$MNT/boot/efi"
mount "$P1" "$MNT/boot/efi"
mkdir -p "$MNT/data"
# Monta la partizione dati del DISCO installato — necessario per scrivere
# config.json nel posto giusto. Senza questo mount, la symlink
# /home/pi/.config/camera-viewer → /data/camera-viewer viene seguita
# nell'ambiente della USB anziché del disco installato.
mount "$P3" "$MNT/data"

# ── Copia sistema ─────────────────────────────────────────────────────────────
echo "  [4/6] Copia sistema (5-15 minuti, dipende dal disco)..."
rsync -aA --delete --info=progress2 \
    --exclude='/proc/*'          --exclude='/sys/*'     --exclude='/dev/*' \
    --exclude='/run/*'           --exclude='/tmp/*'     --exclude='/mnt/*' \
    --exclude='/media/*'         --exclude='/data/*'    --exclude='/swap.img' \
    --exclude='/boot/efi' \
    --exclude='/usr/lib/live' \
    --exclude='/home/pi/.config/camera-viewer/*' \
    / "$MNT/"
echo ""

# ── Configurazione sistema installato ─────────────────────────────────────────
echo "  [5/6] Configurazione..."

# Rileva utente desktop del sistema installato (primo con UID >= 1000)
KIOSK_USER=$(awk -F: '$3 >= 1000 && $3 < 65534 && $6 ~ /^\/home/ {print $1; exit}' \
    "$MNT/etc/passwd")
KIOSK_USER="${KIOSK_USER:-ubuntu}"   # fallback sicuro se /etc/passwd non ha utenti desktop
KIOSK_HOME="/home/${KIOSK_USER}"
echo "  Utente kiosk: $KIOSK_USER  (home: $KIOSK_HOME)"

# fstab con UUID del nuovo disco
tee "$MNT/etc/fstab" > /dev/null << FSTAB
UUID=$SYS_UUID  /          ext4  defaults,noatime  0 1
UUID=$EFI_UUID  /boot/efi  vfat  defaults          0 2
LABEL=cv-data   /data      ext4  defaults,noatime  0 2
FSTAB

# Assicura che lightdm usi il vero utente kiosk
if [ -f "$MNT/etc/lightdm/lightdm.conf.d/50-autologin.conf" ]; then
    sed -i "s/autologin-user=.*/autologin-user=${KIOSK_USER}/" \
        "$MNT/etc/lightdm/lightdm.conf.d/50-autologin.conf"
    echo "  ✓ autologin-user → $KIOSK_USER"
fi

# Config iniziale pulita: admin/admin + must_change_password
<<<<<<< HEAD
# /home/pi/.config/camera-viewer è un symlink → /data/camera-viewer (assoluto).
# Montiamo la partizione dati e scriviamo il config direttamente lì.
mount "$P3" "$MNT/data"
=======
# IMPORTANTE: scrive su /data/camera-viewer della partizione dati INSTALLATA
# (già montata a $MNT/data), NON segue la symlink nell'ambiente della USB.
>>>>>>> 9a1ea17 (NOTICK fix(kiosk): fix black screen after install)
mkdir -p "$MNT/data/camera-viewer"
python3 -c "
import json, uuid
try:
    from werkzeug.security import generate_password_hash
except ImportError:
    import subprocess
    subprocess.run(['pip3','install','werkzeug','-q'], capture_output=True)
    from werkzeug.security import generate_password_hash
cfg = {
    'cameras': [], 'screens': [],
    'settings': {'kiosk_mode': True, 'reconnect_delay_ms': 5000, 'render_fps': 25},
    'site_name': 'Camera Viewer',
    'vpn_profiles': [],
    'license_key': '',
    'users': [{'id': uuid.uuid4().hex[:8], 'username': 'admin',
        'password_hash': generate_password_hash('admin'),
        'role': 'admin', 'must_change_password': True}]
}
json.dump(cfg, open('/tmp/cv-init-config.json', 'w'), indent=2)
print('  Config creato.')
"
cp /tmp/cv-init-config.json "$MNT/data/camera-viewer/config.json"
chown -R 1000:1000 "$MNT/data/camera-viewer/"
<<<<<<< HEAD
umount "$MNT/data"
=======
echo "  ✓ config.json scritto su partizione dati del disco installato"
>>>>>>> 9a1ea17 (NOTICK fix(kiosk): fix black screen after install)

# Patch camera-webconfig.service: sostituisci KIOSK_USER_PLACEHOLDER con l'utente reale
if [ -f "$MNT/etc/systemd/system/camera-webconfig.service" ]; then
    sed -i "s/KIOSK_USER_PLACEHOLDER/$KIOSK_USER/g" \
        "$MNT/etc/systemd/system/camera-webconfig.service"
    echo "  ✓ camera-webconfig.service: User → $KIOSK_USER"
fi

# Rimuovi il servizio installer dall'installazione finale
# (non ha senso avere "Installa" nel GRUB del sistema già installato)
rm -f "$MNT/etc/systemd/system/multi-user.target.wants/cv-installer.service"
# Rimuovi la voce installer dal GRUB del sistema installato
rm -f "$MNT/etc/grub.d/40_custom"

# ── Bootloader ────────────────────────────────────────────────────────────────
echo "  [6/6] Installazione bootloader..."
for d in dev dev/pts proc sys run; do
    mount --bind "/$d" "$MNT/$d" 2>/dev/null || true
done

# Rileva modalità firmware (UEFI vs BIOS legacy).
# mount --bind /sys non propaga i submount, quindi montiamo efivarfs a parte:
# serve a efibootmgr (chiamato da grub-install) per scrivere la voce NVRAM.
if [ -d /sys/firmware/efi ]; then
    FW_MODE="uefi"
    mkdir -p "$MNT/sys/firmware/efi/efivars"
    if ! mount -t efivarfs efivarfs "$MNT/sys/firmware/efi/efivars" 2>/dev/null; then
        echo -e "  ${Y}⚠  efivarfs non montato: la voce NVRAM potrebbe non essere creata."
        echo -e "     Si userà il fallback removibile EFI/BOOT/BOOTX64.EFI.${E}"
    fi
else
    FW_MODE="bios"
fi
echo "  Modalità firmware rilevata: $FW_MODE"

# Remove live-boot initramfs hook directly on the installed filesystem.
# apt-get purge inside chroot is unreliable (no set -e, dpkg locks, pre-rm scripts).
# Deleting the hook file before update-initramfs is simpler and guaranteed.
rm -f "$MNT/usr/share/initramfs-tools/hooks/live"

chroot "$MNT" bash -c "
set -eo pipefail
echo '  Rigenerazione initramfs senza live-boot...'
update-initramfs -u -k all 2>&1 | tail -3
# nosplash: evita lo schermo nero di Plymouth.
sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT=\"quiet loglevel=3 nosplash\"/' \
    /etc/default/grub
# Force VGA text mode so the GRUB menu is always visible, even if gfxterm
# fails to initialize on the target hardware.
grep -q '^GRUB_TERMINAL' /etc/default/grub \
    || echo 'GRUB_TERMINAL=console' >> /etc/default/grub
if [ '$FW_MODE' = 'uefi' ]; then
    # 1) Voce NVRAM 'CameraViewer' tramite lo shim FIRMATO (compatibile Secure Boot).
    #    Crea EFI/CameraViewer/{shimx64,grubx64}.efi + voce di boot nel firmware.
    grub-install --target=x86_64-efi --efi-directory=/boot/efi \
        --bootloader-id=CameraViewer --recheck 2>&1 | tail -3
    # 2) Fallback removibile (EFI/BOOT/BOOTX64.EFI = shim firmato) per i firmware
    #    che non avviano dalla NVRAM sui dischi fissi. Anch'esso firmato.
    grub-install --target=x86_64-efi --efi-directory=/boot/efi \
        --removable --recheck 2>&1 | tail -3
else
    # BIOS legacy: il layout GPT NON ha una BIOS boot partition (flag bios_grub),
    # quindi grub i386-pc non può embeddare core.img → disco non avviabile.
    # Falliamo subito invece di produrre un disco silenziosamente rotto.
    echo 'ERRORE: avvio BIOS legacy non supportato su questo layout.' >&2
    echo 'Abilita la modalità UEFI nel BIOS del PC e ripeti installazione.' >&2
    exit 1
fi
# update-grub: separiamo l'output dal filtro cosmetico. grep senza match o il
# SIGPIPE di 'head' farebbero fallire la pipe con pipefail attivo → falso errore.
update-grub > /tmp/cv-update-grub.log 2>&1
grep -E 'Found|done|Generating' /tmp/cv-update-grub.log | head -5 || true
echo GRUB_OK
"

# Write an explicit grub.cfg in each EFI directory so GRUB can find its config
# by filesystem LABEL even if grub-probe embedded the wrong prefix inside the
# chroot (it reads /proc/mounts from the host, which shows the host mountpoints,
# and may not resolve the correct root UUID).
# GRUB EFI falls back to grub.cfg in the same directory as the binary when the
# embedded prefix lookup fails — this ensures the fallback always works.
for _EFI_DIR in "$MNT/boot/efi/EFI/CameraViewer" "$MNT/boot/efi/EFI/BOOT"; do
    [ -d "$_EFI_DIR" ] || continue
    cat > "$_EFI_DIR/grub.cfg" << 'EOFGRUB'
search --no-floppy --label --set=root cv-system
set prefix=($root)/boot/grub
configfile ($root)/boot/grub/grub.cfg
EOFGRUB
done

umount "$MNT/sys/firmware/efi/efivars" 2>/dev/null || true
for d in run sys proc dev/pts dev; do umount "$MNT/$d" 2>/dev/null || true; done
umount "$MNT/data"
umount "$MNT/boot/efi"
umount "$MNT"

# ── Completato ────────────────────────────────────────────────────────────────
echo ""
echo -e "${G}${B}╔══════════════════════════════════════════════════════════╗${E}"
echo -e "${G}${B}║  ✅ Camera Viewer installato correttamente!              ║${E}"
echo -e "${G}${B}╠══════════════════════════════════════════════════════════╣${E}"
echo -e "${G}${B}║  1. RIMUOVI LA USB DAL PC prima del riavvio!             ║${E}"
echo -e "${G}${B}║  2. Il PC si riavvierà tra 30 secondi                    ║${E}"
echo -e "${G}${B}║  3. Camera Viewer parte dal disco interno                ║${E}"
echo -e "${G}${B}║                                                          ║${E}"
echo -e "${G}${B}║  Primo accesso al portale:                               ║${E}"
echo -e "${G}${B}║    → IP mostrato sullo schermo                           ║${E}"
echo -e "${G}${B}║    → Login: admin / admin  (cambia subito!)              ║${E}"
echo -e "${G}${B}╚══════════════════════════════════════════════════════════╝${E}"
echo ""
echo -e "  ${R}${B}⚠  Rimuovi la USB ora, poi attendi il riavvio.${E}"
echo -ne "  Riavvio in: "
for i in $(seq 30 -1 1); do
    echo -ne "${B}${i}${E} "
    sleep 1
done
echo ""
# Disable ERR trap before reboot: the USB may produce I/O errors during shutdown,
# causing reboot to return non-zero. The installation is already complete at this point.
trap - ERR
sync
reboot -f 2>/dev/null || systemctl reboot --force 2>/dev/null || reboot
