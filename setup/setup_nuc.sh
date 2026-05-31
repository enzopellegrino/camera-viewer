#!/bin/bash
# =============================================================================
# Camera Viewer — Setup NUC6 i5 (Ubuntu 24.04 LTS)
#
# Questo script viene eseguito automaticamente al primo avvio dopo
# l'installazione di Ubuntu via autoinstall.
#
# Può essere eseguito anche manualmente su qualsiasi NUC:
#   sudo bash setup/setup_nuc.sh
#
# NON contiene IP hardcoded: funziona su qualsiasi rete.
# =============================================================================
set -euo pipefail

LOG="/home/pi/setup-nuc.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== Camera Viewer NUC6 Setup: $(date) ==="

# -----------------------------------------------------------------------------
# 1. Attendi connessione internet
# -----------------------------------------------------------------------------
echo "[1/9] Attesa connessione internet..."
for i in $(seq 1 30); do
    curl -sf --max-time 5 https://github.com > /dev/null 2>&1 && echo "     Connesso." && break
    echo "     Tentativo $i/30..."
    sleep 5
done

# -----------------------------------------------------------------------------
# 2. Pacchetti di sistema
# -----------------------------------------------------------------------------
echo "[2/9] Installazione pacchetti di sistema..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y \
    mpv \
    python3-pip python3-venv python3-dev \
    python3-flask \
    openvpn wireguard-tools \
    xorg openbox lightdm \
    i965-va-driver intel-media-va-driver vainfo libva-drm2 libva-x11-2 \
    unclutter x11-xserver-utils feh \
    git curl wget net-tools iproute2 \
    network-manager

# -----------------------------------------------------------------------------
# 3. Clone / aggiorna repo
# -----------------------------------------------------------------------------
echo "[3/9] Clone repository..."
cd /home/pi
REPO_URL="https://github.com/enzopellegrino/camera-viewer.git"
BRANCH="main"

if [ ! -d "camera-viewer" ]; then
    sudo -u pi git clone -b "$BRANCH" "$REPO_URL" camera-viewer
else
    sudo -u pi git -C camera-viewer fetch origin
    sudo -u pi git -C camera-viewer checkout "$BRANCH"
    sudo -u pi git -C camera-viewer pull
fi

# -----------------------------------------------------------------------------
# 4. Python venv + dipendenze
# -----------------------------------------------------------------------------
echo "[4/9] Python venv..."
cd /home/pi/camera-viewer
sudo -u pi python3 -m venv .venv
sudo -u pi .venv/bin/pip install --upgrade pip -q
sudo -u pi .venv/bin/pip install -r requirements.txt -q

# -----------------------------------------------------------------------------
# 5. Script di sistema (cv-*)
# -----------------------------------------------------------------------------
echo "[5/9] Installazione script cv-*..."
install -m 755 raspberry/scripts/cv-mode           /usr/local/sbin/cv-mode
install -m 755 raspberry/scripts/cv-viewer-launch  /usr/local/sbin/cv-viewer-launch
install -m 755 raspberry/scripts/cv-vpn            /usr/local/sbin/cv-vpn
install -m 755 raspberry/scripts/cv-ovpn           /usr/local/sbin/cv-ovpn
install -m 440 raspberry/scripts/sudoers-cv-helpers /etc/sudoers.d/cv-helpers

# -----------------------------------------------------------------------------
# 6. Stub pcmanfm → feh (server.py usa pcmanfm per lo sfondo del desktop)
# -----------------------------------------------------------------------------
cat > /usr/local/bin/pcmanfm << 'EOF'
#!/bin/bash
# Stub: redirige pcmanfm --set-wallpaper a feh (usato da camera-viewer su openbox)
if [[ "${1:-}" == "--set-wallpaper" ]]; then
    for arg in "$@"; do
        [[ "$arg" == --* ]] && continue
        feh --bg-fill "$arg" 2>/dev/null || true
        break
    done
fi
EOF
chmod +x /usr/local/bin/pcmanfm

# -----------------------------------------------------------------------------
# 7. LightDM: autologin come pi con sessione openbox
# -----------------------------------------------------------------------------
echo "[6/9] Configurazione display manager..."
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
Comment=Log in using the Openbox window manager
Exec=/usr/bin/openbox-session
TryExec=/usr/bin/openbox-session
Type=Application
EOF

# -----------------------------------------------------------------------------
# 8. Openbox autostart
# -----------------------------------------------------------------------------
echo "[7/9] Configurazione openbox autostart..."
sudo -u pi mkdir -p /home/pi/.config/openbox

cat > /home/pi/.config/openbox/autostart << 'EOF'
# Camera Viewer Kiosk — openbox autostart

# Intel HD 520 (NUC6 Skylake): VAAPI hardware decode
export LIBVA_DRIVER_NAME=iHD
export CV_HWDEC_BACKEND=vaapi

# Disabilita screen blanking
xset s off
xset -dpms
xset s noblank

# Nascondi cursore dopo 1 secondo di inattività
unclutter -idle 1 -root &

# Avvia il viewer (cv-viewer-launch controlla se ci sono telecamere configurate)
/usr/local/sbin/cv-viewer-launch &
EOF
chown pi:pi /home/pi/.config/openbox/autostart

# Directory config condivisa viewer ↔ portal
sudo -u pi mkdir -p /home/pi/.config/camera-viewer

# -----------------------------------------------------------------------------
# 9. Servizi systemd
# -----------------------------------------------------------------------------
echo "[8/9] Installazione servizi systemd..."
install -m 644 raspberry/systemd/camera-webconfig.service \
    /etc/systemd/system/camera-webconfig.service

systemctl daemon-reload
systemctl enable lightdm
systemctl enable camera-webconfig

# -----------------------------------------------------------------------------
# Verifica VAAPI
# -----------------------------------------------------------------------------
echo "[9/9] Verifica VAAPI..."
LIBVA_DRIVER_NAME=iHD vainfo 2>&1 | head -8 || \
vainfo 2>&1 | head -8 || echo "(vainfo non disponibile)"

# -----------------------------------------------------------------------------
# Cleanup e riavvio
# -----------------------------------------------------------------------------
touch /etc/cv-firstboot.done
rm -f /home/pi/cv-firstboot.sh

IP=$(hostname -I | awk '{print $1}')
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  Camera Viewer NUC6 — setup completato!         ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  Portal web: http://${IP}:80              ║"
echo "║  SSH:        ssh pi@${IP}                 ║"
echo "║                                                  ║"
echo "║  Dopo il riavvio:                                ║"
echo "║  → apri http://${IP} dal browser         ║"
echo "║  → aggiungi telecamere                           ║"
echo "║  → premi 'Avvia' → le vedi sulla TV             ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "Riavvio tra 10 secondi..."
sleep 10
reboot
