#!/bin/bash
# =============================================================================
# Camera Viewer — Setup NUC6 i5 (Ubuntu 24.04 LTS)
#
# Uso manuale (dopo clone repo):
#   cd ~/camera-viewer && bash setup/setup_nuc.sh
#
# Normalmente eseguito automaticamente al primo avvio via cv-firstboot.service.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"
CURRENT_USER="${SUDO_USER:-$(whoami)}"

echo "=== Camera Viewer — Setup NUC6 i5 ==="
echo "App dir: $APP_DIR"
echo "Utente: $CURRENT_USER"

# Verifica VAAPI Intel
if command -v vainfo &>/dev/null; then
    echo ""
    echo "--- VAAPI info ---"
    LIBVA_DRIVER_NAME=iHD vainfo 2>&1 | head -15 || \
    vainfo 2>&1 | head -15 || true
    echo "------------------"
    echo ""
fi

# Python venv + dipendenze
echo "[1/4] Python venv..."
sudo -u "$CURRENT_USER" python3 -m venv .venv
sudo -u "$CURRENT_USER" .venv/bin/pip install --upgrade pip -q
sudo -u "$CURRENT_USER" .venv/bin/pip install -r requirements.txt -q

# Script di sistema
echo "[2/4] Script cv-*..."
sudo install -m 755 raspberry/scripts/cv-mode          /usr/local/sbin/cv-mode
sudo install -m 755 raspberry/scripts/cv-viewer-launch  /usr/local/sbin/cv-viewer-launch
sudo install -m 755 raspberry/scripts/cv-vpn            /usr/local/sbin/cv-vpn
sudo install -m 755 raspberry/scripts/cv-ovpn           /usr/local/sbin/cv-ovpn
sudo install -m 440 raspberry/scripts/sudoers-cv-helpers /etc/sudoers.d/cv-helpers

# Stub pcmanfm → feh
echo "[3/4] pcmanfm stub..."
sudo tee /usr/local/bin/pcmanfm > /dev/null << 'EOF'
#!/bin/bash
if [[ "${1:-}" == "--set-wallpaper" ]]; then
    img=""
    for arg in "$@"; do
        [[ "$arg" == --* ]] && continue
        img="$arg"
    done
    [ -n "$img" ] && feh --bg-fill "$img" 2>/dev/null || true
fi
EOF
sudo chmod +x /usr/local/bin/pcmanfm

# Servizi systemd
echo "[4/4] Servizi systemd..."
sudo install -m 644 raspberry/systemd/camera-webconfig.service \
    /etc/systemd/system/camera-webconfig.service
sudo systemctl daemon-reload
sudo systemctl enable camera-webconfig

echo ""
echo "✅ Setup completato."
echo "   Configura openbox autostart e riavvia lightdm per il kiosk."
echo "   Log portal: journalctl -u camera-webconfig -f"
