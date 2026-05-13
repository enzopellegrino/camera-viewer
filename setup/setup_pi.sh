#!/bin/bash
set -e
cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"
CURRENT_USER="$(whoami)"

echo "=== Camera Viewer - Setup Raspberry Pi ==="

# GStreamer (backend QtMultimedia su Linux) + utils
sudo apt update -q
sudo apt install -y \
  python3-pip python3-venv \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \
  gstreamer1.0-libav \
  unclutter x11-xserver-utils -q

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Disabilita blanking schermo
AUTOSTART="/etc/xdg/lxsession/LXDE-pi/autostart"
if [ -f "$AUTOSTART" ]; then
    sudo grep -q "xset s off"   "$AUTOSTART" || echo "@xset s off"                 | sudo tee -a "$AUTOSTART" > /dev/null
    sudo grep -q "xset -dpms"   "$AUTOSTART" || echo "@xset -dpms"                 | sudo tee -a "$AUTOSTART" > /dev/null
    sudo grep -q "unclutter"    "$AUTOSTART" || echo "@unclutter -idle 0.1 -root"  | sudo tee -a "$AUTOSTART" > /dev/null
fi

# Servizio systemd
sudo tee /etc/systemd/system/camera-viewer.service > /dev/null <<EOF
[Unit]
Description=Camera Viewer Kiosk
After=graphical-session.target
Wants=graphical-session.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${APP_DIR}
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/${CURRENT_USER}/.Xauthority
Environment=QT_MEDIA_BACKEND=gstreamer
ExecStartPre=/bin/sleep 5
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable camera-viewer.service

echo ""
echo "✅ Setup Raspberry Pi completato!"
echo ""
echo "  sudo systemctl start camera-viewer    # avvia subito"
echo "  journalctl -u camera-viewer -f        # log live"
