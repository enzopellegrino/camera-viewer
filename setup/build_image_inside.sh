#!/bin/bash
# =============================================================================
# Camera Viewer — Build script (gira nella VM Podman su macOS)
#
# Crea un'immagine disco Live USB con 3 partizioni:
#   1. EFI    (512MB)  — GRUB bootloader
#   2. System (8GB)    — Ubuntu minimal + Camera Viewer
#   3. Data   (resto)  — Config persistente (telecamere, VPN, ecc.)
#
# NON installa nulla sull'hard disk del PC — gira dalla USB.
# =============================================================================
set -euo pipefail

VERSION="${1:-2.0}"
OUTPUT_DIR="${2:-/tmp/cv-output}"
APP_TGZ="${3:-$OUTPUT_DIR/camera-viewer-app.tar.gz}"
IMG_FILE="$OUTPUT_DIR/camera-viewer-v${VERSION}.img"

mkdir -p "$OUTPUT_DIR"
IMG_SIZE_MB=6144    # 6GB immagine raw (compressa xz → ~600MB)
EFI_SIZE_MB=256     # EFI 256MB
SYSTEM_SIZE_MB=5120 # Sistema 5GB (necessario per Ubuntu + PySide6 + pacchetti)
# DATA occupa il resto (~768MB, espandibile dopo il primo avvio)

log()  { echo -e "\n  \033[1m>>> $*\033[0m"; }
ok()   { echo -e "  \033[32m✓\033[0m $*"; }
info() { echo -e "  \033[36m→\033[0m $*"; }

echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║   Camera Viewer v${VERSION} — Image Builder         ║"
echo "  ║   Build dentro container Podman                 ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo ""

# ── Installa strumenti build ──────────────────────────────────────────────────
log "Installazione strumenti build..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
mkdir -p /var/cache/apt/archives
apt-get install -y -q --no-install-recommends \
    debootstrap parted dosfstools e2fsprogs \
    grub-efi-amd64-bin grub-pc-bin grub2-common \
    xz-utils rsync
apt-get clean
ok "Strumenti installati"

# ── Crea immagine disco raw ───────────────────────────────────────────────────
log "Creazione immagine disco (${IMG_SIZE_MB}MB)..."
dd if=/dev/zero of="$IMG_FILE" bs=1M count=$IMG_SIZE_MB status=progress
ok "Immagine raw creata: $(ls -lh "$IMG_FILE" | awk '{print $5}')"

# ── Partiziona ────────────────────────────────────────────────────────────────
log "Partizionamento (EFI + System + Data)..."
parted -s "$IMG_FILE" mklabel gpt
parted -s "$IMG_FILE" mkpart EFI   fat32  1MiB                ${EFI_SIZE_MB}MiB
parted -s "$IMG_FILE" mkpart System ext4 ${EFI_SIZE_MB}MiB    $((EFI_SIZE_MB + SYSTEM_SIZE_MB))MiB
parted -s "$IMG_FILE" mkpart Data   ext4 $((EFI_SIZE_MB + SYSTEM_SIZE_MB))MiB 100%
parted -s "$IMG_FILE" set 1 esp on
ok "3 partizioni create"

# ── Loop device e formattazione ───────────────────────────────────────────────
log "Montaggio e formattazione (VM Linux — loop device disponibili)..."

# Nella VM Podman siamo su Linux reale: losetup funziona
LOOP=$(losetup -f --show -P "$IMG_FILE")
info "Loop device: $LOOP"

# Aspetta che le partizioni siano riconosciute dal kernel
partprobe "$LOOP" 2>/dev/null || true
sleep 1
ls "${LOOP}p1" "${LOOP}p2" "${LOOP}p3" || {
    info "Retry partprobe..."
    sleep 2
    ls "${LOOP}p1" "${LOOP}p2" "${LOOP}p3" || exit 1
}

mkfs.vfat -F32 -n "CV-EFI"    "${LOOP}p1"
mkfs.ext4 -L  "cv-system"     "${LOOP}p2" -q
mkfs.ext4 -L  "cv-data"       "${LOOP}p3" -q
ok "Filesystem creati"

mkdir -p /target /cv-data
mount "${LOOP}p2" /target          # monta root prima
mkdir -p /target/boot/efi          # crea la dir DENTRO il filesystem montato
mount "${LOOP}p1" /target/boot/efi # poi monta EFI
mount "${LOOP}p3" /cv-data

# ── Debootstrap Ubuntu 24.04 minimal ─────────────────────────────────────────
log "Debootstrap Ubuntu 24.04 minimal (richiede 5-10 min)..."
debootstrap \
    --variant=minbase \
    --arch=amd64 \
    --components=main,universe \
    noble /target \
    http://archive.ubuntu.com/ubuntu/
ok "Ubuntu base installato"

# ── Configura chroot ──────────────────────────────────────────────────────────
log "Configurazione sistema..."

# fstab
cat > /target/etc/fstab << 'EOF'
LABEL=cv-system  /          ext4  defaults,noatime  0 1
LABEL=CV-EFI     /boot/efi  vfat  defaults          0 2
LABEL=cv-data    /data      ext4  defaults,noatime  0 2
EOF

# hosts / hostname
echo "camera-viewer" > /target/etc/hostname
cat > /target/etc/hosts << 'EOF'
127.0.0.1  localhost
127.0.1.1  camera-viewer
EOF
# Aggiungi hostname del container (evita warning 'unable to resolve host' in sudo)
echo "127.0.0.1 $(hostname 2>/dev/null || echo builder)" >> /target/etc/hosts

# Mount per chroot
for d in dev dev/pts proc sys run; do
    mount --bind /$d /target/$d
done

# ── Installa pacchetti dentro chroot ──────────────────────────────────────────
log "Installazione pacchetti Camera Viewer (richiede 10-15 min)..."
chroot /target /bin/bash << 'CHROOT'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# Repository e aggiornamenti
echo "deb http://archive.ubuntu.com/ubuntu noble main universe" > /etc/apt/sources.list
echo "deb http://archive.ubuntu.com/ubuntu noble-updates main universe" >> /etc/apt/sources.list
echo "deb http://security.ubuntu.com/ubuntu noble-security main universe" >> /etc/apt/sources.list
apt-get update -q

# Kernel e bootloader
apt-get install -y -q --no-install-recommends linux-image-generic shim-signed grub-efi-amd64-signed
apt-get clean

# Sistema base
apt-get install -y -q --no-install-recommends \
    systemd systemd-sysv dbus udev \
    network-manager openssh-server \
    curl wget git ca-certificates \
    sudo locales tzdata

# Display
apt-get install -y -q --no-install-recommends \
    xorg openbox lightdm \
    libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-xkb1 libxkbcommon-x11-0

# Video
apt-get install -y -q --no-install-recommends mpv \
    i965-va-driver intel-media-va-driver \
    mesa-va-drivers vainfo libva-drm2 libva-x11-2

# Python base — PySide6 viene installato via pip nel venv (non disponibile in apt)
apt-get install -y -q --no-install-recommends \
    python3-pip python3-venv python3-dev \
    python3-flask python3-cryptography python3-pil
apt-get clean

# VPN
apt-get install -y -q --no-install-recommends openvpn wireguard-tools

# Utilities
apt-get install -y -q --no-install-recommends \
    unclutter x11-xserver-utils feh \
    pciutils net-tools iproute2 \
    htop nano

# Locale
locale-gen it_IT.UTF-8 en_US.UTF-8
update-locale LANG=it_IT.UTF-8

# Timezone
ln -sf /usr/share/zoneinfo/Europe/Rome /etc/localtime

# Utente pi
useradd -m -s /bin/bash -G sudo,audio,video,plugdev pi
echo "pi:N1computer@2019" | chpasswd

# Sudo senza password per pi
echo "pi ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/pi
chmod 440 /etc/sudoers.d/pi

# Gruppo nopasswdlogin per autologin LightDM
groupadd -f nopasswdlogin
usermod -a -G nopasswdlogin pi

# Directory dati su partizione separata
mkdir -p /data
echo "# cv-data montata da /etc/fstab" > /data/.keep

# Symlink config Camera Viewer → partizione dati (persistente!)
mkdir -p /home/pi/.config
ln -sf /data/camera-viewer /home/pi/.config/camera-viewer

# Link display-manager
ln -sf /usr/lib/systemd/system/lightdm.service \
       /etc/systemd/system/display-manager.service

echo "Pacchetti installati."
CHROOT
ok "Pacchetti installati"

# ── Copia app Camera Viewer ───────────────────────────────────────────────────
log "Copia app Camera Viewer..."
if [ -f "$APP_TGZ" ]; then
    mkdir -p /target/home/pi/camera-viewer
    tar xzf "$APP_TGZ" \
        -C /target/home/pi/camera-viewer/ \
        --warning=no-unknown-keyword 2>/dev/null || \
    tar xzf /output/camera-viewer-app.tar.gz \
        -C /target/home/pi/camera-viewer/ 2>/dev/null || true
    chroot /target chown -R pi:pi /home/pi/camera-viewer
    ok "App copiata"
else
    echo "  ⚠  App non trovata in /output/ — skip"
fi

# ── Configura Camera Viewer ───────────────────────────────────────────────────
log "Configurazione Camera Viewer..."
chroot /target /bin/bash << 'CHROOT'
set -euo pipefail

cd /home/pi/camera-viewer || exit 0

# Python venv
# venv — PySide6 va installato via pip (non è in apt Ubuntu 24.04)
# Cache pip → /output (montato dalla VM che ha 43GB liberi)
export PIP_CACHE_DIR=/output/pip-cache
mkdir -p /output/pip-cache
sudo -H -u pi python3 -m venv .venv
sudo -H -u pi .venv/bin/pip install --upgrade pip -q
sudo -H -u pi .venv/bin/pip install -r requirements.txt -q \
    --cache-dir /output/pip-cache
sudo -H -u pi .venv/bin/pip install flask -q \
    --cache-dir /output/pip-cache

# Script di sistema
[ -f raspberry/scripts/cv-mode ] && \
    install -m 755 raspberry/scripts/cv-mode           /usr/local/sbin/cv-mode
[ -f raspberry/scripts/cv-viewer-launch ] && \
    install -m 755 raspberry/scripts/cv-viewer-launch  /usr/local/sbin/cv-viewer-launch
[ -f raspberry/scripts/cv-vpn ] && \
    install -m 755 raspberry/scripts/cv-vpn            /usr/local/sbin/cv-vpn
[ -f raspberry/scripts/cv-ovpn ] && \
    install -m 755 raspberry/scripts/cv-ovpn           /usr/local/sbin/cv-ovpn
[ -f raspberry/scripts/sudoers-cv-helpers ] && \
    install -m 440 raspberry/scripts/sudoers-cv-helpers /etc/sudoers.d/cv-helpers

# VAAPI: aggiungi env per Intel (default, si può cambiare a runtime)
sed -i "/export QT_QPA_PLATFORM/a export CV_HWDEC_BACKEND=vaapi\nexport LIBVA_DRIVER_NAME=iHD" \
    /usr/local/sbin/cv-viewer-launch 2>/dev/null || true

# Stub pcmanfm → feh
cat > /usr/local/bin/pcmanfm << 'EOF'
#!/bin/bash
if [[ "${1:-}" == "--set-wallpaper" ]]; then
    for arg in "$@"; do [[ "$arg" == --* ]] && continue; feh --bg-fill "$arg" 2>/dev/null || true; break; fi
fi
EOF
chmod +x /usr/local/bin/pcmanfm

# Servizi systemd
[ -f raspberry/systemd/camera-webconfig.service ] && \
    install -m 644 raspberry/systemd/camera-webconfig.service \
        /etc/systemd/system/camera-webconfig.service && \
    systemctl enable camera-webconfig

# Modalità rete: ethernet normale o hotspot WiFi se nessun ethernet
[ -f raspberry/scripts/cv-network-mode ] && \
    install -m 755 raspberry/scripts/cv-network-mode \
        /usr/local/sbin/cv-network-mode
[ -f raspberry/systemd/camera-network-mode.service ] && \
    install -m 644 raspberry/systemd/camera-network-mode.service \
        /etc/systemd/system/camera-network-mode.service && \
    systemctl enable camera-network-mode

# Installa iptables per captive portal redirect in AP mode
apt-get install -y -q --no-install-recommends iptables 2>/dev/null || true

# LightDM autologin
mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/50-autologin.conf << 'EOF'
[Seat:*]
autologin-user=pi
autologin-user-timeout=0
user-session=openbox
EOF

# Openbox sessione
cat > /usr/share/xsessions/openbox.desktop << 'EOF'
[Desktop Entry]
Name=Openbox
Exec=/usr/bin/openbox-session
TryExec=/usr/bin/openbox-session
Type=Application
EOF

# Openbox autostart
mkdir -p /home/pi/.config/openbox
cat > /home/pi/.config/openbox/autostart << 'EOF'
xset s off; xset -dpms; xset s noblank
unclutter -idle 1 -root &
/usr/local/sbin/cv-viewer-launch &
EOF
chown -R pi:pi /home/pi/.config

# Console login message
cat > /etc/issue << 'EOF'

  ┌─────────────────────────────────────────────┐
  │   🎥   Camera Viewer v2.0                   │
  │        di Enzo Pellegrino                   │
  │        http://\4                            │
  └─────────────────────────────────────────────┘

EOF

# Script setup GPU al primo avvio (rileva Intel/AMD/altro)
cat > /usr/local/sbin/cv-detect-gpu << 'EOF'
#!/bin/bash
# Rileva GPU e configura VAAPI al primo avvio
GPU=$(lspci 2>/dev/null | grep -iE 'vga|display|3d' | head -1)
LAUNCHER=/usr/local/sbin/cv-viewer-launch

if echo "$GPU" | grep -qi intel; then
    BACKEND=vaapi; DRIVER=iHD
elif echo "$GPU" | grep -qiE 'amd|radeon'; then
    BACKEND=vaapi; DRIVER=radeonsi
else
    BACKEND=""; DRIVER=""
fi

if [ -n "$BACKEND" ]; then
    sed -i "s/CV_HWDEC_BACKEND=.*/CV_HWDEC_BACKEND=${BACKEND}/" "$LAUNCHER" 2>/dev/null
    sed -i "s/LIBVA_DRIVER_NAME=.*/LIBVA_DRIVER_NAME=${DRIVER}/" "$LAUNCHER" 2>/dev/null
fi
touch /etc/cv-gpu-detected
EOF
chmod +x /usr/local/sbin/cv-detect-gpu

cat > /etc/systemd/system/cv-detect-gpu.service << 'EOF'
[Unit]
Description=Camera Viewer GPU Detection
After=multi-user.target
ConditionPathExists=!/etc/cv-gpu-detected

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/cv-detect-gpu
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl enable cv-detect-gpu

# ── Espansione automatica partizione Data al primo avvio ──────────────
# La partizione /data occupa solo ~768MB nell'immagine.
# Questo script espande p3 per usare tutto lo spazio libero della USB/disco.
cat > /usr/local/sbin/cv-expand-data << 'EOF'
#!/bin/bash
# Espande la partizione data (p3) per riempire tutto il disco.
# Eseguito una sola volta al primo avvio.
set -e

# Trova il disco e la partizione p3
DISK=$(lsblk -no PKNAME $(findmnt -n -o SOURCE /data) 2>/dev/null | head -1)
[ -z "$DISK" ] && exit 0

DISK="/dev/$DISK"
PART="${DISK}3"

# Verifica spazio libero (almeno 500MB per espandere)
FREE_MB=$(parted -sm "$DISK" unit MB print free 2>/dev/null | grep "free" | tail -1 | awk -F: '{print int($4)}' || echo 0)
[ "$FREE_MB" -lt 500 ] && echo "Poco spazio libero, skip" && exit 0

echo "Espansione /data su $PART (spazio libero: ${FREE_MB}MB)..."
parted -s "$DISK" resizepart 3 100% 2>/dev/null || true
sleep 1
resize2fs "$PART" 2>/dev/null || true
echo "Espansione completata."
touch /etc/cv-data-expanded
EOF
chmod +x /usr/local/sbin/cv-expand-data

cat > /etc/systemd/system/cv-expand-data.service << 'EOF'
[Unit]
Description=Camera Viewer — Espansione partizione dati
After=local-fs.target
ConditionPathExists=!/etc/cv-data-expanded

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/cv-expand-data
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl enable cv-expand-data

echo "Camera Viewer configurato."
CHROOT
ok "Camera Viewer configurato"

# ── Installa GRUB EFI ─────────────────────────────────────────────────────────
log "Installazione bootloader GRUB..."

# grub-install VA eseguito FUORI dal chroot con il loop device reale
# così può scrivere correttamente sull'EFI partition
grub-install --target=x86_64-efi \
    --efi-directory=/target/boot/efi \
    --boot-directory=/target/boot \
    --removable \
    --recheck \
    "$LOOP" 2>&1 | tail -3

# Trova i file kernel reali (non i symlink che potrebbero non funzionare in GRUB)
KERNEL=$(ls /target/boot/vmlinuz-*-generic 2>/dev/null | sort -V | tail -1 | sed 's|/target||')
INITRD=$(ls /target/boot/initrd.img-*-generic 2>/dev/null | sort -V | tail -1 | sed 's|/target||')
info "Kernel: $KERNEL"
info "Initrd: $INITRD"

# grub.cfg brandizzato Camera Viewer con path reali del kernel
cat > /target/boot/grub/grub.cfg << EOF
set timeout=8
set default=0

set color_normal=cyan/black
set color_highlight=black/cyan
set menu_color_normal=white/black
set menu_color_highlight=black/cyan

echo "  Camera Viewer v2.0"
echo "  di Enzo Pellegrino"

menuentry " Avvia Camera Viewer" {
    search --no-floppy --label --set=root cv-system
    linux  ${KERNEL} root=LABEL=cv-system rw quiet splash loglevel=3
    initrd ${INITRD}
}
menuentry " Camera Viewer (modalita sicura, nomodeset)" {
    search --no-floppy --label --set=root cv-system
    linux  ${KERNEL} root=LABEL=cv-system rw nomodeset loglevel=3
    initrd ${INITRD}
}
menuentry " Shell GRUB (debug)" {
    terminal_input console
    terminal_output console
}
EOF

info "grub.cfg scritto con kernel: $KERNEL"
ok "GRUB installato"

# ── Prepara partizione dati ───────────────────────────────────────────────────
log "Configurazione partizione dati persistenti..."
mkdir -p /cv-data/camera-viewer
chmod 755 /cv-data/camera-viewer
# Config iniziale Camera Viewer (vuota, verrà popolata al primo avvio)
cat > /cv-data/camera-viewer/config.json << 'EOF'
{
  "cameras": [],
  "screens": [],
  "settings": {"kiosk_mode": true, "reconnect_delay_ms": 5000, "render_fps": 25},
  "site_name": "Camera Viewer",
  "users": []
}
EOF
ok "Partizione dati pronta"

# ── Pulizia ───────────────────────────────────────────────────────────────────
log "Pulizia cache..."
chroot /target apt-get clean
chroot /target apt-get autoremove -y -q
rm -rf /target/tmp/* /target/var/cache/apt/archives/*.deb
sync

# ── Smonta ────────────────────────────────────────────────────────────────────
log "Smontaggio..."
for d in dev/pts dev proc sys run; do
    umount /target/$d 2>/dev/null || true
done
umount /target/boot/efi 2>/dev/null || true
umount /cv-data 2>/dev/null || true
umount /target 2>/dev/null || true
sync
losetup -d "$LOOP" 2>/dev/null || true
ok "Smontaggio completato"

# ── Comprimi con xz ───────────────────────────────────────────────────────────
log "Compressione immagine..."
RAW_SIZE=$(ls -lh "$IMG_FILE" | awk '{print $5}')
info "Raw size: $RAW_SIZE"
# Usa xz -6 per default (buon bilanciamento velocità/dimensione)
# Per massima compressione usa: XZ_LEVEL=9 bash make-image.sh
XZ_LEVEL="${XZ_LEVEL:-6}"
info "Livello compressione: -${XZ_LEVEL} (per produzione usa XZ_LEVEL=9)"
xz -${XZ_LEVEL} -T0 "$IMG_FILE"
COMPRESSED="${IMG_FILE}.xz"
COMP_SIZE=$(ls -lh "$COMPRESSED" | awk '{print $5}')
ok "Compressione completata: $COMP_SIZE (era $RAW_SIZE)"

echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║  ✅ Build completato!                            ║"
echo "  ║  File: camera-viewer-v${VERSION}.img.xz           ║"
echo "  ║  Size: ${COMP_SIZE}                                     ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo ""
