#!/bin/bash
# =============================================================================
# Camera Viewer — Universal First Boot Setup
#
# Funziona su qualsiasi PC/NUC x86_64 con Ubuntu Server 24.04.
# Rileva automaticamente la GPU e configura VAAPI se disponibile.
# L'app viene estratta dal tar.gz in /home/pi/ (incluso nell'USB installer)
# oppure clonata da GitHub come fallback.
#
# NON eseguire manualmente in produzione — lanciato da cloud-init al primo avvio.
# Per test manuali: sudo bash setup/setup_nuc.sh
# =============================================================================
set -euo pipefail

LOG="/home/pi/setup-nuc.log"
exec > >(tee -a "$LOG") 2>&1

# Banner ASCII
echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │                                             │"
echo "  │   🎥   C A M E R A   V I E W E R   2.0    │"
echo "  │        Sistema di Monitoraggio Video        │"
echo "  │                                             │"
echo "  │        Creato da Enzo Pellegrino           │"
echo "  │                                             │"
echo "  └─────────────────────────────────────────────┘"
echo ""
echo "  Setup avviato: $(date)"
echo ""

# ── 0. Splash console al boot successivo (Plymouth text theme) ──────────────
# Mostra "Camera Viewer" sul boot screen invece del logo Ubuntu
mkdir -p /usr/share/plymouth/themes/camera-viewer
cat > /usr/share/plymouth/themes/camera-viewer/camera-viewer.plymouth << 'EOF'
[Plymouth Theme]
Name=Camera Viewer
Description=Camera Viewer Boot Screen
ModuleName=details
EOF
cat > /usr/share/plymouth/themes/camera-viewer/camera-viewer.script << 'EOF'
Window.SetBackgroundTopColor(0.05, 0.06, 0.10);
Window.SetBackgroundBottomColor(0.05, 0.06, 0.10);
EOF
update-alternatives --install \
    /usr/share/plymouth/themes/default.plymouth \
    default.plymouth \
    /usr/share/plymouth/themes/camera-viewer/camera-viewer.plymouth 200 2>/dev/null || true
update-initramfs -u -k all 2>/dev/null || true

# Console login message
cat > /etc/issue << 'EOF'

  ┌─────────────────────────────────────────────┐
  │   🎥   Camera Viewer v2.0                   │
  │        Sistema di Monitoraggio Video        │
  │        http://\4                            │
  └─────────────────────────────────────────────┘

EOF

# ── 1. Attendi internet (serve per apt) ──────────────────────────────────────
echo ""
echo "[1/9] Attesa connessione internet..."
for i in $(seq 1 30); do
    curl -sf --max-time 5 http://deb.debian.org > /dev/null 2>&1 && echo "     ✓ Connesso." && break
    echo "     Tentativo $i/30..."
    sleep 5
done

# ── 2. Rileva GPU e pacchetti grafici ────────────────────────────────────────
echo ""
echo "[2/9] Rilevamento GPU..."
GPU_INFO=$(lspci 2>/dev/null | grep -iE 'vga|display|3d controller' || true)
echo "     $GPU_INFO"

CV_HWDEC_BACKEND=""
LIBVA_DRIVER_NAME=""
VAAPI_PKGS=""

if echo "$GPU_INFO" | grep -qi intel; then
    echo "     → Intel GPU — installazione driver VAAPI iHD"
    VAAPI_PKGS="i965-va-driver intel-media-va-driver vainfo libva-drm2 libva-x11-2"
    CV_HWDEC_BACKEND="vaapi"
    LIBVA_DRIVER_NAME="iHD"
elif echo "$GPU_INFO" | grep -qiE 'amd|radeon|advanced micro'; then
    echo "     → AMD GPU — installazione driver VAAPI Mesa"
    VAAPI_PKGS="mesa-va-drivers vainfo libva-drm2 libva-x11-2"
    CV_HWDEC_BACKEND="vaapi"
    LIBVA_DRIVER_NAME="radeonsi"
else
    echo "     → GPU non riconosciuta — SW decode (funziona su qualsiasi hardware)"
fi

# ── 3. Pacchetti di sistema ──────────────────────────────────────────────────
echo ""
echo "[3/9] Installazione pacchetti di sistema..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y \
    mpv \
    python3-pip python3-venv python3-dev \
    python3-flask \
    openvpn wireguard-tools \
    xorg openbox lightdm \
    libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-xkb1 libxkbcommon-x11-0 \
    unclutter x11-xserver-utils feh \
    pciutils git curl wget net-tools iproute2 \
    network-manager \
    ${VAAPI_PKGS}

# ── 4. Estrai app o clone GitHub ─────────────────────────────────────────────
echo ""
if [ -f /home/pi/camera-viewer.tar.gz ]; then
    echo "[4/9] Estrazione app dall'USB..."
    rm -rf /home/pi/camera-viewer
    mkdir -p /home/pi/camera-viewer
    tar xzf /home/pi/camera-viewer.tar.gz -C /home/pi/camera-viewer/ 2>/dev/null || \
    tar xzf /home/pi/camera-viewer.tar.gz -C /home/pi/camera-viewer/ --warning=no-unknown-keyword 2>/dev/null || true
    chown -R pi:pi /home/pi/camera-viewer
    rm -f /home/pi/camera-viewer.tar.gz
    echo "     ✓ App estratta"
else
    echo "[4/9] Fallback: clone da GitHub..."
    sudo -u pi git clone -b main \
        https://github.com/enzopellegrino/camera-viewer.git \
        /home/pi/camera-viewer 2>&1 | tail -3
fi

# Verifica che l'app sia presente
if [ ! -f /home/pi/camera-viewer/main.py ]; then
    echo "ERRORE: app non trovata in /home/pi/camera-viewer/"
    exit 1
fi

# ── 5. Python venv ───────────────────────────────────────────────────────────
echo ""
echo "[5/9] Python venv..."
cd /home/pi/camera-viewer
sudo -H -u pi python3 -m venv .venv
sudo -H -u pi .venv/bin/pip install --upgrade pip -q
sudo -H -u pi .venv/bin/pip install -r requirements.txt -q
sudo -H -u pi .venv/bin/pip install flask -q
echo "     ✓ venv pronto"

# ── 6. Script di sistema cv-* ────────────────────────────────────────────────
echo ""
echo "[6/9] Script cv-*..."
install -m 755 raspberry/scripts/cv-mode           /usr/local/sbin/cv-mode
install -m 755 raspberry/scripts/cv-viewer-launch  /usr/local/sbin/cv-viewer-launch
install -m 755 raspberry/scripts/cv-vpn            /usr/local/sbin/cv-vpn
install -m 755 raspberry/scripts/cv-ovpn           /usr/local/sbin/cv-ovpn
install -m 440 raspberry/scripts/sudoers-cv-helpers /etc/sudoers.d/cv-helpers

# Aggiungi env VAAPI specifico al cv-viewer-launch per questa macchina
if [ -n "$CV_HWDEC_BACKEND" ]; then
    # Inserisce le variabili GPU dopo la riga 'export QT_QPA_PLATFORM=xcb'
    sed -i "/export QT_QPA_PLATFORM/a export CV_HWDEC_BACKEND=${CV_HWDEC_BACKEND}\nexport LIBVA_DRIVER_NAME=${LIBVA_DRIVER_NAME}" \
        /usr/local/sbin/cv-viewer-launch
    echo "     ✓ VAAPI configurato: backend=${CV_HWDEC_BACKEND}, driver=${LIBVA_DRIVER_NAME}"
fi

# Stub pcmanfm → feh
cat > /usr/local/bin/pcmanfm << 'EOF'
#!/bin/bash
if [[ "${1:-}" == "--set-wallpaper" ]]; then
    for arg in "$@"; do [[ "$arg" == --* ]] && continue; feh --bg-fill "$arg" 2>/dev/null || true; break; fi
fi
EOF
chmod +x /usr/local/bin/pcmanfm

# ── 7. Display manager: LightDM + openbox ────────────────────────────────────
echo ""
echo "[7/9] Display manager..."

mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/50-autologin.conf << 'EOF'
[Seat:*]
autologin-user=pi
autologin-user-timeout=0
user-session=openbox
EOF

cat > /usr/share/xsessions/openbox.desktop << 'EOF'
[Desktop Entry]
Name=Openbox
Exec=/usr/bin/openbox-session
TryExec=/usr/bin/openbox-session
Type=Application
EOF

mkdir -p /home/pi/.config/openbox
cat > /home/pi/.config/openbox/autostart << EOF
# Camera Viewer Kiosk — openbox autostart
xset s off; xset -dpms; xset s noblank
unclutter -idle 1 -root &
/usr/local/sbin/cv-viewer-launch &
EOF
chown -R pi:pi /home/pi/.config
mkdir -p /home/pi/.config/camera-viewer
chown pi:pi /home/pi/.config/camera-viewer

# Rimuovi .Xauthority stale
rm -f /home/pi/.Xauthority

# Gruppo nopasswdlogin per autologin LightDM
groupadd -f nopasswdlogin
usermod -a -G nopasswdlogin pi

# Symlink LightDM come display-manager di default
ln -sf /usr/lib/systemd/system/lightdm.service \
       /etc/systemd/system/display-manager.service

# ── 8. Servizi systemd ───────────────────────────────────────────────────────
echo ""
echo "[8/9] Servizi systemd..."
install -m 644 raspberry/systemd/camera-webconfig.service \
    /etc/systemd/system/camera-webconfig.service

systemctl daemon-reload
systemctl enable lightdm
systemctl enable camera-webconfig

# ── 9. Verifica VAAPI (se applicabile) ──────────────────────────────────────
echo ""
echo "[9/9] Verifica finale..."
if [ -n "$LIBVA_DRIVER_NAME" ]; then
    LIBVA_DRIVER_NAME=$LIBVA_DRIVER_NAME vainfo 2>&1 | head -6 || \
        vainfo 2>&1 | head -6 || echo "     (vainfo non disponibile)"
else
    echo "     SW decode — nessuna verifica VAAPI necessaria"
fi

# ── Cleanup e riavvio ────────────────────────────────────────────────────────
touch /etc/cv-firstboot.done
rm -f /home/pi/setup-nuc.sh

IP=$(hostname -I | awk '{print $1}')
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  ✅ Camera Viewer — Setup completato!        ║"
echo "╠══════════════════════════════════════════════╣"
echo "║  Portal:  http://${IP}               ║"
echo "║  SSH:     ssh pi@${IP}              ║"
echo "║  Login:   admin / admin              ║"
echo "║           (cambia da Impostazioni → Utenti) ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "Riavvio in 10 secondi..."
sleep 10
reboot
