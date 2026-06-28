#!/bin/bash
# =============================================================================
# Camera Viewer — ISO Builder
#
# Crea una Live ISO standard (UEFI + BIOS legacy):
#   /live/filesystem.squashfs  — rootfs Ubuntu compresso con xz
#   /live/vmlinuz + initrd.img — kernel e initramfs con live-boot
#   GRUB menu: avvio live oppure installazione su disco
#
# Gira su Ubuntu Linux (anche in Docker --privileged su Mac via build_iso.sh).
# Output: camera-viewer-vX.X.iso (~700-900MB, file unico)
#
# Uso diretto:
#   sudo bash setup/build_image_inside.sh <VERSION> <OUTPUT_DIR> <APP_TGZ>
# =============================================================================
set -euo pipefail

VERSION="${1:-3.0}"
OUTPUT_DIR="${2:-/tmp/cv-output}"
APP_TGZ="${3:-$OUTPUT_DIR/camera-viewer-app.tar.gz}"
ISO_FILE="$OUTPUT_DIR/camera-viewer-v${VERSION}.iso"
ROOTFS=/tmp/cv-rootfs
STAGING=/tmp/cv-iso-staging

mkdir -p "$OUTPUT_DIR" "$ROOTFS" "$STAGING"

log()  { echo -e "\n  \033[1m>>> $*\033[0m"; }
ok()   { echo -e "  \033[32m✓\033[0m $*"; }
info() { echo -e "  \033[36m→\033[0m $*"; }

echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║   Camera Viewer v${VERSION} — ISO Builder          ║"
echo "  ║   Live ISO: UEFI + BIOS, squashfs + live-boot   ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo ""

# ── Strumenti build ───────────────────────────────────────────────────────────
log "Installazione strumenti build..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -q 2>/dev/null
apt-get install -y -q --no-install-recommends \
    debootstrap squashfs-tools xorriso \
    grub-efi-amd64-bin grub-pc-bin grub2-common \
    mtools rsync 2>/dev/null
apt-get clean 2>/dev/null
ok "Strumenti installati"

# ── Debootstrap Ubuntu 24.04 ──────────────────────────────────────────────────
log "Debootstrap Ubuntu 24.04 minimal (5-10 min)..."
debootstrap \
    --variant=minbase \
    --arch=amd64 \
    --components=main,universe \
    noble "$ROOTFS" \
    http://archive.ubuntu.com/ubuntu/
ok "Ubuntu base installato"

# ── Configurazione base ───────────────────────────────────────────────────────
log "Configurazione sistema..."

echo "camera-viewer" > "$ROOTFS/etc/hostname"
cat > "$ROOTFS/etc/hosts" << 'EOF'
127.0.0.1  localhost
127.0.1.1  camera-viewer
EOF
echo "127.0.0.1 $(hostname 2>/dev/null || echo builder)" >> "$ROOTFS/etc/hosts"

# fstab minimale per live (sovrascritta dall'installer su disco)
cat > "$ROOTFS/etc/fstab" << 'EOF'
# Live mode: filesystem in RAM tramite overlayfs (live-boot)
# Su disco questo file viene riscritto dall'installer con gli UUID reali
EOF

# Mount bind per chroot
for d in dev dev/pts proc sys run; do
    mount --bind /$d "$ROOTFS/$d"
done

# ── Pacchetti nel chroot ──────────────────────────────────────────────────────
log "Installazione pacchetti Camera Viewer (10-15 min)..."
chroot "$ROOTFS" /bin/bash << 'CHROOT'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "deb http://archive.ubuntu.com/ubuntu noble main universe" > /etc/apt/sources.list
echo "deb http://archive.ubuntu.com/ubuntu noble-updates main universe" >> /etc/apt/sources.list
echo "deb http://security.ubuntu.com/ubuntu noble-security main universe" >> /etc/apt/sources.list
apt-get update -q

# Kernel + live-boot (essenziale: gestisce mount squashfs + overlayfs)
apt-get install -y -q --no-install-recommends \
    linux-image-generic initramfs-tools \
    live-boot live-boot-initramfs-tools \
    shim-signed grub-efi-amd64-signed
KERNEL_VER=$(ls /boot/vmlinuz-*-generic 2>/dev/null | sort -V | tail -1 | sed 's|/boot/vmlinuz-||')
[ -n "$KERNEL_VER" ] && update-initramfs -u -k "$KERNEL_VER" 2>&1 | tail -3 || true
apt-get clean

# Sistema base
apt-get install -y -q --no-install-recommends \
    systemd systemd-sysv dbus udev \
    network-manager openssh-server \
    curl wget git ca-certificates \
    sudo locales tzdata

# Display
apt-get install -y -q --no-install-recommends \
    xorg openbox lightdm plymouth \
    libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-xkb1 libxkbcommon-x11-0

# Video: mpv + VA-API Intel (iHD) e Mesa (AMD/altri)
apt-get install -y -q --no-install-recommends mpv \
    intel-media-va-driver \
    mesa-va-drivers vainfo libva-drm2 libva-x11-2

# Python: PySide6 via pip nel venv (non disponibile in apt su Noble)
apt-get install -y -q --no-install-recommends \
    python3-pip python3-venv \
    python3-flask python3-cryptography python3-pil
apt-get clean

# Utilities
apt-get install -y -q --no-install-recommends \
    unclutter x11-xserver-utils feh xterm \
    pciutils net-tools iproute2 iptables \
    htop nano parted e2fsprogs
apt-get clean

# Locale / Timezone
locale-gen it_IT.UTF-8 en_US.UTF-8
update-locale LANG=it_IT.UTF-8
ln -sf /usr/share/zoneinfo/Europe/Rome /etc/localtime

# Utente pi — password bloccata nell'immagine, generata random al primo avvio
useradd -m -s /bin/bash -G sudo,audio,video,plugdev pi
passwd -l pi
groupadd -f nopasswdlogin
usermod -aG nopasswdlogin pi

# Directory dati (su disco installato verrà montata su /data)
mkdir -p /data
mkdir -p /home/pi/.config
ln -sf /data/camera-viewer /home/pi/.config/camera-viewer

# Display manager
ln -sf /usr/lib/systemd/system/lightdm.service \
       /etc/systemd/system/display-manager.service

# Maschera servizi che bloccano il boot
mkdir -p /etc/cloud && touch /etc/cloud/cloud-init.disabled
for svc in NetworkManager-wait-online systemd-networkd-wait-online \
           apt-daily apt-daily-upgrade unattended-upgrades \
           cloud-init cloud-init-local cloud-config cloud-final \
           systemd-networkd; do
    ln -sf /dev/null /etc/systemd/system/${svc}.service 2>/dev/null || true
done
for timer in apt-daily apt-daily-upgrade; do
    ln -sf /dev/null /etc/systemd/system/${timer}.timer 2>/dev/null || true
done
# network-online.target NON mascherato: masking rompe NM su Ubuntu 24.04.
# I wait-service (NM-wait-online, networkd-wait-online) sono già mascherati sopra.

# Servizio SSH: genera password random al primo avvio
cat > /usr/local/sbin/cv-firstboot-ssh << 'SCRIPT'
#!/bin/bash
set -euo pipefail
PASSWORD=$(openssl rand -base64 12 | tr -d '/+=' | head -c 12)
echo "pi:${PASSWORD}" | chpasswd
passwd --expire pi
echo "$PASSWORD" > /etc/cv-ssh-password
chmod 600 /etc/cv-ssh-password
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
Description=Camera Viewer — genera password SSH al primo avvio
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

echo "Pacchetti installati."
CHROOT
ok "Pacchetti installati"

# ── Copia app ─────────────────────────────────────────────────────────────────
log "Copia app Camera Viewer..."
if [ -f "$APP_TGZ" ]; then
    mkdir -p "$ROOTFS/home/pi/camera-viewer"
    tar xzf "$APP_TGZ" -C "$ROOTFS/home/pi/camera-viewer/" \
        --warning=no-unknown-keyword 2>/dev/null || true
    chroot "$ROOTFS" chown -R pi:pi /home/pi/camera-viewer
    ok "App copiata"
else
    echo "  ⚠  App non trovata — skip"
fi

# ── Configura Camera Viewer ───────────────────────────────────────────────────
log "Configurazione Camera Viewer..."
chroot "$ROOTFS" /bin/bash << 'CHROOT'
set -euo pipefail
cd /home/pi/camera-viewer || exit 0

export PIP_CACHE_DIR=/tmp/pip-cache
mkdir -p /tmp/pip-cache
sudo -H -u pi python3 -m venv .venv
sudo -H -u pi .venv/bin/pip install --upgrade pip -q
[ -f requirements.txt ] && grep -v "pyinstaller" requirements.txt > /tmp/cv-requirements-kiosk.txt || touch /tmp/cv-requirements-kiosk.txt
sudo -H -u pi .venv/bin/pip install -r /tmp/cv-requirements-kiosk.txt -q \
    --cache-dir /tmp/pip-cache
sudo -H -u pi .venv/bin/pip install flask -q --cache-dir /tmp/pip-cache

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

# VAAPI: default Intel, cv-detect-gpu lo corregge al primo avvio
sed -i "/export QT_QPA_PLATFORM/a export CV_HWDEC_BACKEND=vaapi\nexport LIBVA_DRIVER_NAME=iHD" \
    /usr/local/sbin/cv-viewer-launch 2>/dev/null || true

# Stub pcmanfm → feh (per wallpaper openbox)
cat > /usr/local/bin/pcmanfm << 'EOF'
#!/bin/bash
if [[ "${1:-}" == "--set-wallpaper" ]]; then
    for arg in "$@"; do [[ "$arg" == --* ]] && continue; feh --bg-fill "$arg" 2>/dev/null || true; break; fi
fi
EOF
chmod +x /usr/local/bin/pcmanfm

# Servizi systemd
for svc in camera-webconfig camera-bootmode camera-network-mode; do
    svcfile="raspberry/systemd/${svc}.service"
    [ -f "$svcfile" ] || continue
    install -m 644 "$svcfile" "/etc/systemd/system/${svc}.service"
    sed -i "s/KIOSK_USER_PLACEHOLDER/pi/g" "/etc/systemd/system/${svc}.service"
    systemctl enable "$svc"
done

[ -f raspberry/scripts/cv-network-mode ] && \
    install -m 755 raspberry/scripts/cv-network-mode /usr/local/sbin/cv-network-mode
[ -f raspberry/scripts/cv-nm-dispatcher ] && \
    install -m 755 raspberry/scripts/cv-nm-dispatcher \
        /etc/NetworkManager/dispatcher.d/99-cv-hotspot

# Installer su disco (copiato nell'immagine, usato dalla voce "Installa" di GRUB)
[ -f tools/install-camera-viewer.sh ] && \
    install -m 755 tools/install-camera-viewer.sh /usr/local/bin/install-camera-viewer.sh

# cv-installer.service: si attiva solo con cv_install=1 nel cmdline kernel
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

# LightDM autologin
mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/50-autologin.conf << 'EOF'
[Seat:*]
autologin-user=pi
autologin-user-timeout=0
user-session=openbox
EOF

printf '#%%PAM-1.0\nauth    required   pam_env.so readenv=1 user_readenv=0\nauth    sufficient pam_succeed_if.so user ingroup nopasswdlogin\nauth    required   pam_permit.so\n@include common-account\n@include common-session\n' \
  > /etc/pam.d/lightdm-autologin

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

mkdir -p /home/pi/.config/openbox
cat > /home/pi/.config/openbox/autostart << 'EOF'
xset s off; xset -dpms; xset s noblank
unclutter -idle 1 -root &
/usr/local/sbin/cv-viewer-launch &
EOF
chown -R pi:pi /home/pi/.config

# GPU detection al primo avvio (rileva Intel/AMD e configura VAAPI)
cat > /usr/local/sbin/cv-detect-gpu << 'EOF'
#!/bin/bash
GPU=$(lspci 2>/dev/null | grep -iE 'vga|display|3d' | head -1)
LAUNCHER=/usr/local/sbin/cv-viewer-launch
if echo "$GPU" | grep -qi intel; then
    BACKEND=vaapi; DRIVER=iHD
elif echo "$GPU" | grep -qiE 'amd|radeon'; then
    BACKEND=vaapi; DRIVER=radeonsi
else
    BACKEND=""; DRIVER=""
fi
[ -n "$BACKEND" ] && \
    sed -i "s/CV_HWDEC_BACKEND=.*/CV_HWDEC_BACKEND=${BACKEND}/" "$LAUNCHER" 2>/dev/null && \
    sed -i "s/LIBVA_DRIVER_NAME=.*/LIBVA_DRIVER_NAME=${DRIVER}/" "$LAUNCHER" 2>/dev/null
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

# Espansione automatica /data al primo avvio su disco installato
cat > /usr/local/sbin/cv-expand-data << 'EOF'
#!/bin/bash
set -e
DISK=$(lsblk -no PKNAME $(findmnt -n -o SOURCE /data) 2>/dev/null | head -1)
[ -z "$DISK" ] && exit 0
DISK="/dev/$DISK"; PART="${DISK}3"
FREE_MB=$(parted -sm "$DISK" unit MB print free 2>/dev/null | grep "free" | tail -1 | awk -F: '{print int($4)}' || echo 0)
[ "$FREE_MB" -lt 500 ] && exit 0
parted -s "$DISK" resizepart 3 100% 2>/dev/null || true
sleep 1
resize2fs "$PART" 2>/dev/null || true
touch /etc/cv-data-expanded
EOF
chmod +x /usr/local/sbin/cv-expand-data

cat > /etc/systemd/system/cv-expand-data.service << 'EOF'
[Unit]
Description=Camera Viewer — Espansione partizione dati al primo avvio
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

# ── Pulizia ───────────────────────────────────────────────────────────────────
log "Pulizia cache e file non necessari..."
chroot "$ROOTFS" apt-get clean
chroot "$ROOTFS" apt-get autoremove -y -q 2>/dev/null || true
rm -rf "$ROOTFS/var/lib/apt/lists/"*
rm -rf "$ROOTFS/var/cache/apt/archives/"*.deb
rm -rf "$ROOTFS/tmp/"*
rm -rf /tmp/pip-cache "$ROOTFS/tmp/pip-cache" "$ROOTFS/root/.cache" "$ROOTFS/home/pi/.cache"
find "$ROOTFS/usr/share/locale" -mindepth 1 -maxdepth 1 -type d \
    ! -name 'it' ! -name 'it_IT' ! -name 'en' ! -name 'en_US' \
    -exec rm -rf {} + 2>/dev/null || true
rm -rf "$ROOTFS/usr/share/doc/"* "$ROOTFS/usr/share/man/"* "$ROOTFS/usr/share/info/"*
find "$ROOTFS/home/pi/camera-viewer/.venv" \
    -path "*/Qt/translations/*.qm" -delete 2>/dev/null || true
find "$ROOTFS" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$ROOTFS" -name "*.pyc" -delete 2>/dev/null || true

log "Strip debug symbols dal venv..."
find "$ROOTFS/home/pi/camera-viewer/.venv" -name "*.so*" -type f \
    -exec strip --strip-debug {} + 2>/dev/null || true
VENV_SIZE=$(du -sh "$ROOTFS/home/pi/camera-viewer/.venv" 2>/dev/null | awk '{print $1}' || echo "?")
info "Venv dopo strip: ${VENV_SIZE}"

# Smonta chroot binds — -l (lazy) gestisce submount di systemd/udev creati durante l'install
for d in dev/pts dev proc sys run; do
    umount -l "$ROOTFS/$d" 2>/dev/null || true
done
sync
ok "Pulizia completata"

# ── Staging ISO ───────────────────────────────────────────────────────────────
log "Preparazione staging ISO..."
mkdir -p "$STAGING/live" "$STAGING/boot/grub"

# Copia kernel e initrd nella directory live
KERNEL=$(ls "$ROOTFS/boot/vmlinuz-"*-generic 2>/dev/null | sort -V | tail -1)
INITRD=$(ls "$ROOTFS/boot/initrd.img-"*-generic 2>/dev/null | sort -V | tail -1)
[ -n "$KERNEL" ] || { echo "ERRORE: nessun kernel trovato nel rootfs"; exit 1; }
[ -n "$INITRD" ] || { echo "ERRORE: nessun initrd trovato nel rootfs"; exit 1; }
info "Kernel: $(basename "$KERNEL")"
info "Initrd: $(basename "$INITRD")"
cp "$KERNEL" "$STAGING/live/vmlinuz"
cp "$INITRD" "$STAGING/live/initrd.img"

# Dimensione non compressa (usata dai progress bar degli installer)
du -sx --block-size=1 "$ROOTFS" | awk '{print $1}' > "$STAGING/live/filesystem.size"

# SquashFS: rootfs compresso con xz — il cuore della ISO
log "Creazione squashfs rootfs (2-5 min)..."
mksquashfs "$ROOTFS" "$STAGING/live/filesystem.squashfs" \
    -comp xz -Xbcj x86 -b 1M -no-progress \
    -e boot/efi \
    2>/dev/null
SQUASH_SIZE=$(du -sh "$STAGING/live/filesystem.squashfs" | awk '{print $1}')
ok "SquashFS: $SQUASH_SIZE"

# GRUB config per live boot
# boot=live  → live-boot monta squashfs + overlayfs in RAM
# cv_install=1 → cv-installer.service avvia l'installer su disco
cat > "$STAGING/boot/grub/grub.cfg" << EOF
set timeout=15
set default=0
set menu_color_normal=white/black
set menu_color_highlight=black/white

menuentry "  Avvia Camera Viewer v${VERSION} (Live)" {
    search --no-floppy --label --set=root CV-LIVE
    linux  /live/vmlinuz boot=live quiet loglevel=3 label=CV-LIVE
    initrd /live/initrd.img
}
menuentry "  Installa Camera Viewer v${VERSION} su disco interno" {
    search --no-floppy --label --set=root CV-LIVE
    linux  /live/vmlinuz boot=live quiet loglevel=3 label=CV-LIVE cv_install=1 systemd.unit=multi-user.target
    initrd /live/initrd.img
}
menuentry "  Modalita sicura (nomodeset)" {
    search --no-floppy --label --set=root CV-LIVE
    linux  /live/vmlinuz boot=live nomodeset loglevel=3 label=CV-LIVE
    initrd /live/initrd.img
}
EOF
ok "GRUB config creato"

# ── Crea ISO ibrida (UEFI + BIOS legacy) ─────────────────────────────────────
# grub-mkrescue gestisce automaticamente:
#   - EFI boot (BOOTX64.EFI embeddato)
#   - BIOS legacy (grub-pc embedded MBR)
#   - Hybrid MBR: la ISO si può scrivere su USB con dd/Etcher/Rufus
log "Creazione ISO ibrida UEFI+BIOS (grub-mkrescue)..."
grub-mkrescue \
    --output="$ISO_FILE" \
    --modules="part_gpt part_msdos fat ext2 normal boot linux search search_label echo all_video video_fb" \
    "$STAGING" \
    -- -volid "CV-LIVE" -joliet -joliet-long -rational-rock \
    2>/dev/null
ISO_SIZE=$(ls -lh "$ISO_FILE" | awk '{print $5}')
ok "ISO creata: $ISO_SIZE"

# Cleanup
rm -rf "$STAGING" "$ROOTFS"

echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║  ✅ Build completato!                            ║"
printf "  ║  File: camera-viewer-v%-4s.iso                ║\n" "${VERSION}"
printf "  ║  Size: %-10s                               ║\n" "${ISO_SIZE}"
echo "  ║                                                  ║"
echo "  ║  Scrivi su USB con:                              ║"
echo "  ║    Balena Etcher  (GUI, Mac/Win/Linux)           ║"
echo "  ║    Rufus          (Windows)                      ║"
echo "  ║    dd if=*.iso of=/dev/sdX bs=4M  (Linux/Mac)   ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo ""
