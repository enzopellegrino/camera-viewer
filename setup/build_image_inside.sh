#!/bin/bash
# =============================================================================
# Camera Viewer — Build script (gira sul NUC via SSH)
#
# Crea un'immagine disco Live USB con 3 partizioni:
#   1. EFI    (256MB)  — GRUB standalone (grub-mkstandalone)
#   2. System (5GB)    — Ubuntu minimal + Camera Viewer
#   3. Data   (resto)  — Config persistente (telecamere, VPN, ecc.)
#
# Gira su Ubuntu x86_64 reale — GRUB, losetup e debootstrap funzionano.
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
SYSTEM_SIZE_MB=5120 # Sistema 5GB
# DATA occupa il resto

log()  { echo -e "\n  \033[1m>>> $*\033[0m"; }
ok()   { echo -e "  \033[32m✓\033[0m $*"; }
info() { echo -e "  \033[36m→\033[0m $*"; }

echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║   Camera Viewer v${VERSION} — Image Builder         ║"
echo "  ║   Build su NUC (Ubuntu x86_64 — GRUB nativo)   ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo ""

# ── Installa strumenti build ──────────────────────────────────────────────────
log "Installazione strumenti build..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -q 2>/dev/null
apt-get install -y -q --no-install-recommends \
    debootstrap parted dosfstools e2fsprogs \
    grub-efi-amd64-bin grub-efi-amd64 grub2-common \
    xz-utils rsync 2>/dev/null
apt-get clean 2>/dev/null
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

# Kernel, initramfs-tools (indispensabile per generare initrd) e bootloader
apt-get install -y -q --no-install-recommends linux-image-generic initramfs-tools shim-signed grub-efi-amd64-signed
# Forza generazione initrd (a volte non parte automaticamente nel chroot)
KERNEL_VER=$(ls /boot/vmlinuz-*-generic 2>/dev/null | sort -V | tail -1 | sed 's|/boot/vmlinuz-||')
[ -n "$KERNEL_VER" ] && update-initramfs -c -k "$KERNEL_VER" 2>&1 | tail -3 || true
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

# Video — i965 è per GPU Intel Broadwell e precedenti (pre-2016), quasi mai usato.
# Manteniamo solo intel-media-va-driver (iHD, moderno) e mesa per AMD/altri.
apt-get install -y -q --no-install-recommends mpv \
    intel-media-va-driver \
    mesa-va-drivers vainfo libva-drm2 libva-x11-2

# Python base — PySide6 viene installato via pip nel venv (non disponibile in apt).
# python3-dev NON serve a runtime (solo per compilare extension C, non usato).
apt-get install -y -q --no-install-recommends \
    python3-pip python3-venv \
    python3-flask python3-cryptography python3-pil
apt-get clean

# VPN — openvpn e wireguard rimossi dall'immagine base per ridurre dimensione.
# Possono essere installati tramite il portale web se necessario.
# apt-get install -y -q --no-install-recommends openvpn wireguard-tools

# Utilities
apt-get install -y -q --no-install-recommends \
    unclutter x11-xserver-utils feh xterm \
    pciutils net-tools iproute2 \
    htop nano

# Locale
locale-gen it_IT.UTF-8 en_US.UTF-8
update-locale LANG=it_IT.UTF-8

# Timezone
ln -sf /usr/share/zoneinfo/Europe/Rome /etc/localtime

# Utente pi — nessuna password hardcodata nel repo
# Una password random viene generata al primo avvio da cv-firstboot-ssh.service
useradd -m -s /bin/bash -G sudo,audio,video,plugdev pi
passwd -l pi  # account bloccato nell'immagine; sbloccato al primo avvio

# nopasswdlogin: richiesto da PAM lightdm-autologin per autologin senza password.
# Senza questo il check pam_succeed_if fallisce → login screen al boot.
groupadd -f nopasswdlogin
usermod -aG nopasswdlogin pi

# Sudo ristretto: solo i comandi cv-* elencati in sudoers-cv-helpers.
# NON usare NOPASSWD:ALL — renderebbe cv-helpers completamente inutile.
# cv-helpers viene installato sotto (install -m 440 sudoers-cv-helpers /etc/sudoers.d/cv-helpers)

# Servizio: genera password SSH random al primo avvio e forza cambio
cat > /usr/local/sbin/cv-firstboot-ssh << 'SCRIPT'
#!/bin/bash
# Genera una password SSH temporanea per l'utente pi al primo avvio.
# L'utente DEVE cambiarla al primo accesso SSH (passwd --expire).
set -euo pipefail

PASSWORD=$(openssl rand -base64 12 | tr -d '/+=' | head -c 12)
echo "pi:${PASSWORD}" | chpasswd
passwd --expire pi

# Salva la password in un file leggibile solo da root
echo "$PASSWORD" > /etc/cv-ssh-password
chmod 600 /etc/cv-ssh-password

# Aggiorna /etc/issue così è visibile sul terminale fisico (Alt+F2)
cat > /etc/issue << EOF

  ┌─────────────────────────────────────────────┐
  │   🎥   Camera Viewer                        │
  │        SSH → utente: pi                     │
  │        Password temporanea: ${PASSWORD}        │
  │        ⚠  Cambia la password al primo login │
  │        http://\4                            │
  └─────────────────────────────────────────────┘

EOF

touch /etc/cv-ssh-firstboot-done
SCRIPT
chmod 755 /usr/local/sbin/cv-firstboot-ssh

cat > /etc/systemd/system/cv-firstboot-ssh.service << 'SVC'
[Unit]
Description=Camera Viewer — genera password SSH temporanea al primo avvio
ConditionPathExists=!/etc/cv-ssh-firstboot-done
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/cv-firstboot-ssh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SVC
systemctl enable cv-firstboot-ssh

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

# ── Disabilita servizi che bloccano il boot senza rete ─────────────────────
# cloud-init: 4 servizi Ubuntu che aspettano rete → fino a 2 min di delay
mkdir -p /etc/cloud
touch /etc/cloud/cloud-init.disabled
# NetworkManager-wait-online + systemd-networkd-wait-online: masked via /dev/null
ln -sf /dev/null /etc/systemd/system/NetworkManager-wait-online.service
ln -sf /dev/null /etc/systemd/system/systemd-networkd-wait-online.service
# apt-daily: download aggiornamenti in background al boot → rallenta
ln -sf /dev/null /etc/systemd/system/apt-daily.service
ln -sf /dev/null /etc/systemd/system/apt-daily-upgrade.service
ln -sf /dev/null /etc/systemd/system/apt-daily.timer
ln -sf /dev/null /etc/systemd/system/apt-daily-upgrade.timer
# unattended-upgrades: upgrade automatici (non voluti su kiosk)
ln -sf /dev/null /etc/systemd/system/unattended-upgrades.service
# network-online.target: nessun servizio attende la rete durante il boot
ln -sf /dev/null /etc/systemd/system/network-online.target
# systemd-networkd: conflitti con NM su Ubuntu 24.04 minimal
ln -sf /dev/null /etc/systemd/system/systemd-networkd.service
# cloud-init: non installato, ma mask precauzionale
mkdir -p /etc/cloud && touch /etc/cloud/cloud-init.disabled
for svc in cloud-init cloud-init-local cloud-config cloud-final; do
    ln -sf /dev/null /etc/systemd/system/${svc}.service
done
echo "✓ Servizi network-wait, apt-daily, network-online.target, cloud-init mascherati"

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

# Python venv — PySide6 installato nel venv (non disponibile via apt Ubuntu 24.04).
# I file .so del venv vengono strippati nella fase di pulizia per ridurre dimensione.
export PIP_CACHE_DIR=/tmp/pip-cache
mkdir -p /tmp/pip-cache
sudo -H -u pi python3 -m venv .venv
sudo -H -u pi .venv/bin/pip install --upgrade pip -q
# pyinstaller escluso: serve solo per build Mac/Windows, non su kiosk Linux
grep -v "pyinstaller" requirements.txt > /tmp/cv-requirements-kiosk.txt
sudo -H -u pi .venv/bin/pip install -r /tmp/cv-requirements-kiosk.txt -q \
    --cache-dir /tmp/pip-cache
sudo -H -u pi .venv/bin/pip install flask -q \
    --cache-dir /tmp/pip-cache

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
    sed -i "s/KIOSK_USER_PLACEHOLDER/pi/g" \
        /etc/systemd/system/camera-webconfig.service && \
    systemctl enable camera-webconfig
[ -f raspberry/systemd/camera-bootmode.service ] && \
    install -m 644 raspberry/systemd/camera-bootmode.service \
        /etc/systemd/system/camera-bootmode.service && \
    systemctl enable camera-bootmode

# Modalità rete: ethernet normale o hotspot WiFi se nessun ethernet
[ -f raspberry/scripts/cv-network-mode ] && \
    install -m 755 raspberry/scripts/cv-network-mode \
        /usr/local/sbin/cv-network-mode

# Dispatcher NetworkManager: hotspot auto quando ethernet cade
[ -f raspberry/scripts/cv-nm-dispatcher ] && \
    install -m 755 raspberry/scripts/cv-nm-dispatcher \
        /etc/NetworkManager/dispatcher.d/99-cv-hotspot
[ -f raspberry/systemd/camera-network-mode.service ] && \
    install -m 644 raspberry/systemd/camera-network-mode.service \
        /etc/systemd/system/camera-network-mode.service && \
    systemctl enable camera-network-mode

# Installer su disco: copiato nell'immagine così l'rsync lo porta sul disco installato
[ -f tools/install-camera-viewer.sh ] && \
    install -m 755 tools/install-camera-viewer.sh \
        /usr/local/bin/install-camera-viewer.sh && \
    echo "✓ install-camera-viewer.sh installato"

# cv-installer.service: avvia l'installer quando cv_install=1 nel cmdline kernel
cat > /etc/systemd/system/cv-installer.service << 'SVCEOF'
[Unit]
Description=Camera Viewer Installer
ConditionKernelCommandLine=cv_install=1
After=local-fs.target
DefaultDependencies=no
Conflicts=camera-bootmode.service camera-webconfig.service lightdm.service

[Service]
Type=oneshot
ExecStartPre=/bin/chvt 1
ExecStart=/usr/local/bin/install-camera-viewer.sh
StandardInput=tty
StandardOutput=tty
StandardError=tty
TTYPath=/dev/tty1
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SVCEOF
systemctl enable cv-installer
echo "✓ cv-installer.service abilitato"

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

# PAM autologin: sufficient + pam_permit fallback.
# pam_succeed_if.so verifica che pi sia nel gruppo nopasswdlogin.
# pam_permit.so garantisce autologin kiosk anche in caso di fallback.
printf '#%%PAM-1.0\nauth    required   pam_env.so readenv=1 user_readenv=0\nauth    sufficient pam_succeed_if.so user ingroup nopasswdlogin\nauth    required   pam_permit.so\n@include common-account\n@include common-session\n' \
  > /etc/pam.d/lightdm-autologin

# LightDM watchdog: riavvia automaticamente se crasha
mkdir -p /etc/systemd/system/lightdm.service.d
printf '[Service]\nRestart=always\nRestartSec=5\n' \
  > /etc/systemd/system/lightdm.service.d/restart.conf

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
  │   🎥   Camera Viewer v${VERSION}                   │
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

# ── Installa GRUB EFI con grub-mkstandalone ───────────────────────────────────
# grub-mkstandalone crea un singolo file EFI autocontenuto con grub.cfg
# integrato dentro — nessun path esterno, funziona su qualsiasi hardware.
log "Creazione bootloader GRUB autocontenuto..."

# Trova kernel e initrd reali
KERNEL=$(ls /target/boot/vmlinuz-*-generic 2>/dev/null | sort -V | tail -1 | sed 's|/target||')
INITRD=$(ls /target/boot/initrd.img-*-generic 2>/dev/null | sort -V | tail -1 | sed 's|/target||')
info "Kernel: $KERNEL"
info "Initrd: $INITRD"

# grub.cfg con kernel reale
cat > /tmp/grub-standalone.cfg << EOF
set timeout=15
set default=0
set menu_color_normal=white/black
set menu_color_highlight=black/white

menuentry "  Installa Camera Viewer v${VERSION} su disco interno" {
    search --no-floppy --label --set=root cv-system
    linux  ${KERNEL} root=LABEL=cv-system rw quiet loglevel=3 cv_install=1 systemd.unit=multi-user.target
    initrd ${INITRD}
}
menuentry "  Avvia Camera Viewer (senza installare)" {
    search --no-floppy --label --set=root cv-system
    linux  ${KERNEL} root=LABEL=cv-system rw quiet loglevel=3
    initrd ${INITRD}
}
menuentry "  Modalita sicura (nomodeset)" {
    search --no-floppy --label --set=root cv-system
    linux  ${KERNEL} root=LABEL=cv-system rw nomodeset loglevel=3
    initrd ${INITRD}
}
EOF

# Crea EFI binary autocontenuto — tutto integrato, nessuna dipendenza esterna
mkdir -p /target/boot/efi/EFI/BOOT
grub-mkstandalone \
    --format=x86_64-efi \
    --output=/target/boot/efi/EFI/BOOT/BOOTX64.EFI \
    --modules="part_gpt part_msdos fat ext2 normal boot linux search search_label echo all_video video_fb" \
    --locales="" \
    --fonts="" \
    "boot/grub/grub.cfg=/tmp/grub-standalone.cfg"

# Copia anche il grub.cfg sulla partizione di sistema (per aggiornamenti futuri)
mkdir -p /target/boot/grub
cp /tmp/grub-standalone.cfg /target/boot/grub/grub.cfg

ok "GRUB autocontenuto creato: $(ls -lh /target/boot/efi/EFI/BOOT/BOOTX64.EFI | awk '{print $5}')"

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
log "Pulizia cache e file non necessari..."
chroot /target apt-get clean
chroot /target apt-get autoremove -y -q
# Apt lists: ricreabili con apt update
rm -rf /target/var/lib/apt/lists/*
# Deb cache
rm -rf /target/var/cache/apt/archives/*.deb
# Tmp
rm -rf /target/tmp/*
# Pip cache (dentro e fuori il chroot)
rm -rf /tmp/pip-cache /target/tmp/pip-cache /target/root/.cache /target/home/pi/.cache
# Locale non necessari (risparmia ~150-200MB)
find /target/usr/share/locale -mindepth 1 -maxdepth 1 -type d \
    ! -name 'it' ! -name 'it_IT' ! -name 'en' ! -name 'en_US' \
    -exec rm -rf {} + 2>/dev/null || true
# Documentazione e man pages
rm -rf /target/usr/share/doc/* /target/usr/share/man/* /target/usr/share/info/*
# Qt translations nel venv (non necessari per kiosk — risparmia ~30MB)
find /target/home/pi/camera-viewer/.venv \
    -path "*/Qt/translations/*.qm" -delete 2>/dev/null || true
# .pyc bytecode cache (ricreati al primo avvio)
find /target -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find /target -name "*.pyc" -delete 2>/dev/null || true

# Strip debug symbols dai .so nel venv (PySide6, OpenCV, cryptography, ecc.)
# Risparmia ~200-400MB di dati nel disco — i debug symbols non servono in produzione.
# --strip-debug: rimuove .debug_info, .debug_aranges, .debug_line ecc.
# Non tocca la symbol table (export table) — le librerie restano pienamente funzionanti.
log "Strip debug symbols dal venv..."
find /target/home/pi/camera-viewer/.venv -name "*.so*" -type f \
    -exec strip --strip-debug {} + 2>/dev/null || true
# Strip anche librerie Qt nel sito-packages PySide6
find /target/home/pi/camera-viewer/.venv -name "libQt*.so*" -type f \
    -exec strip --strip-debug {} + 2>/dev/null || true
VENV_SIZE=$(du -sh /target/home/pi/camera-viewer/.venv 2>/dev/null | awk '{print $1}' || echo "?")
log "Venv dopo strip: ${VENV_SIZE}"

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
