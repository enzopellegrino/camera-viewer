#!/bin/bash
# =============================================================================
# Camera Viewer v2.5 — Universal First Boot Setup
# Creato da Enzo Pellegrino
#
# Output: schermata pulita sullo schermo, log dettagliato in /home/pi/setup-nuc.log
# Per vedere i log tecnici: Alt+F2  |  Per tornare: Alt+F1
# =============================================================================
set -euo pipefail

# Rileva l'utente che ha lanciato sudo (o il primo utente desktop con UID >= 1000)
if [ -n "${SUDO_USER:-}" ]; then
    KIOSK_USER="$SUDO_USER"
else
    KIOSK_USER=$(awk -F: '$3 >= 1000 && $3 < 65534 && $6 ~ /^\/home/ {print $1; exit}' /etc/passwd)
fi
KIOSK_USER="${KIOSK_USER:-ubuntu}"
KIOSK_HOME="/home/$KIOSK_USER"
echo "Setup utente kiosk: $KIOSK_USER  (home: $KIOSK_HOME)"

LOG="$KIOSK_HOME/setup-nuc.log"
START_TS=$(date +%s)

# Se qualcosa va storto, mostra l'errore sullo schermo (non solo nel log)
trap 'echo "" >&3; echo "  ❌  ERRORE al passo: ${BASH_COMMAND}" >&3; echo "  Vedi dettagli: $LOG  (Alt+F2)" >&3' ERR

# Redirect tutto l'output verboso al log, non allo schermo
exec 3>&1 4>&2        # salva stdout/stderr originali
exec >> "$LOG" 2>&1   # tutto al log

# Funzioni per schermata pulita (su fd3 = schermo reale)
_W=50  # larghezza box

box_line()  { printf "  │%-${_W}s│\n" "$1" >&3; }
box_empty() { printf "  │%-${_W}s│\n" "" >&3; }
box_sep()   { printf "  ├%s┤\n" "$(printf '─%.0s' $(seq 1 $_W))" >&3; }
box_top()   { printf "  ┌%s┐\n" "$(printf '─%.0s' $(seq 1 $_W))" >&3; }
box_bot()   { printf "  └%s┘\n" "$(printf '─%.0s' $(seq 1 $_W))" >&3; }

elapsed() {
    local s=$(( $(date +%s) - START_TS ))
    printf "%d min %02d sec" $((s/60)) $((s%60))
}

progress_bar() {
    local pct=$1 width=30
    local filled=$(( pct * width / 100 ))
    local empty=$(( width - filled ))
    local bar=""
    for ((i=0; i<filled; i++)); do bar+="█"; done
    for ((i=0; i<empty; i++)); do bar+="░"; done
    echo "  $bar  ${pct}%"
}

show_screen() {
    local title="$1" phase="$2" pct="$3" check1="${4:-}" check2="${5:-}" check3="${6:-}"
    clear >&3
    echo "" >&3
    box_top
    box_line "  🎥  Camera Viewer v2.5"
    box_line "      Creato da Enzo Pellegrino"
    box_sep
    box_empty
    box_line "  $title"
    box_empty
    box_line "$(progress_bar $pct)"
    box_empty
    [ -n "$check1" ] && box_line "  $check1"
    [ -n "$check2" ] && box_line "  $check2"
    [ -n "$check3" ] && box_line "  $check3"
    [ -n "$phase"  ] && box_line "  ◌ $phase..."
    box_empty
    box_line "  Tempo: $(elapsed)"
    box_empty
    box_line "  [Alt+F2] Log dettagliato"
    box_bot
    echo "" >&3
}

show_done() {
    local ip="${1:-N/A}"
    clear >&3
    echo "" >&3
    box_top
    box_line "  ✅  Camera Viewer — Pronto!"
    box_empty
    box_line "  ✓ Pacchetti installati"
    box_line "  ✓ GPU configurata"
    box_line "  ✓ Portal web attivo"
    box_line "  ✓ Viewer configurato"
    box_sep
    box_empty
    box_line "  Apri dal browser:"
    box_line "  → http://${ip}"
    box_empty
    box_line "  Login:    admin / admin"
    box_line "  ⚠  Cambia subito la password!"
    box_empty
    box_line "  Tempo totale: $(elapsed)"
    box_bot
    echo "" >&3
}

# ── Avvio ────────────────────────────────────────────────────────────────────
echo "════════════════════════════════════════════════" >&3
echo " Camera Viewer — Setup: $(date)" >&3
echo "════════════════════════════════════════════════" >&3
echo "(output completo in $LOG)" >&3
echo "" >&3
echo "Setup avviato: $(date)"

show_screen "Configurazione in corso..." "Avvio sistema" 2

# ── 0. Plymouth branding ─────────────────────────────────────────────────────
mkdir -p /usr/share/plymouth/themes/camera-viewer
cat > /usr/share/plymouth/themes/camera-viewer/camera-viewer.plymouth << 'EOF'
[Plymouth Theme]
Name=Camera Viewer
Description=Camera Viewer Boot Screen
ModuleName=details
EOF
update-alternatives --install \
    /usr/share/plymouth/themes/default.plymouth \
    default.plymouth \
    /usr/share/plymouth/themes/camera-viewer/camera-viewer.plymouth 200 2>/dev/null || true
update-initramfs -u -k all 2>/dev/null || true

# Console login
cat > /etc/issue << 'EOF'

  ┌─────────────────────────────────────────────┐
  │   🎥   Camera Viewer v2.5                   │
  │        di Enzo Pellegrino                   │
  │        http://\4                            │
  └─────────────────────────────────────────────┘

EOF

# ── 1. Attendi internet ───────────────────────────────────────────────────────
show_screen "Configurazione in corso..." "Connessione internet" 5
echo "[1/9] Attesa connessione internet..."
for i in $(seq 1 30); do
    curl -sf --max-time 5 http://deb.debian.org > /dev/null 2>&1 && echo "Internet OK" && break
    echo "  Tentativo $i/30..."
    sleep 5
done

# ── 2. Rileva GPU ────────────────────────────────────────────────────────────
show_screen "Configurazione in corso..." "Rilevamento hardware" 10
echo "[2/9] Rilevamento GPU..."
GPU_INFO=$(lspci 2>/dev/null | grep -iE 'vga|display|3d controller' || true)
echo "GPU trovata: $GPU_INFO"

CV_HWDEC_BACKEND=""
LIBVA_DRIVER_NAME=""
VAAPI_PKGS=""
GPU_LABEL="SW decode (universale)"

if echo "$GPU_INFO" | grep -qi intel; then
    VAAPI_PKGS="i965-va-driver intel-media-va-driver vainfo libva-drm2 libva-x11-2"
    CV_HWDEC_BACKEND="vaapi"
    LIBVA_DRIVER_NAME="iHD"
    GPU_LABEL="Intel GPU — VAAPI iHD"
elif echo "$GPU_INFO" | grep -qiE 'amd|radeon|advanced micro'; then
    VAAPI_PKGS="mesa-va-drivers vainfo libva-drm2 libva-x11-2"
    CV_HWDEC_BACKEND="vaapi"
    LIBVA_DRIVER_NAME="radeonsi"
    GPU_LABEL="AMD GPU — VAAPI Mesa"
fi
echo "GPU configurata: $GPU_LABEL"

# ── 3. Pacchetti ─────────────────────────────────────────────────────────────
show_screen "Configurazione in corso..." "Installazione pacchetti (richiede internet)" 15 \
    "✓ Hardware rilevato: $GPU_LABEL"
echo "[3/9] Installazione pacchetti..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y \
    mpv python3-pip python3-venv python3-dev python3-flask \
    openvpn wireguard-tools \
    xorg openbox lightdm \
    libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-xkb1 libxkbcommon-x11-0 \
    unclutter x11-xserver-utils feh \
    pciutils git curl wget net-tools iproute2 network-manager \
    ${VAAPI_PKGS}
echo "Pacchetti installati."

# ── 4. Estrai app ────────────────────────────────────────────────────────────
show_screen "Configurazione in corso..." "Installazione app" 50 \
    "✓ Hardware: $GPU_LABEL" \
    "✓ Pacchetti installati"
echo "[4/9] App..."
if [ -f "$KIOSK_HOME/camera-viewer.tar.gz" ]; then
    echo "Estrazione da USB..."
    rm -rf "$KIOSK_HOME/camera-viewer"
    mkdir -p "$KIOSK_HOME/camera-viewer"
    tar xzf "$KIOSK_HOME/camera-viewer.tar.gz" -C "$KIOSK_HOME/camera-viewer/" \
        --warning=no-unknown-keyword 2>/dev/null || \
    tar xzf "$KIOSK_HOME/camera-viewer.tar.gz" -C "$KIOSK_HOME/camera-viewer/" 2>/dev/null || true
    chown -R "$KIOSK_USER:$KIOSK_USER" "$KIOSK_HOME/camera-viewer"
    rm -f "$KIOSK_HOME/camera-viewer.tar.gz"
else
    echo "Fallback: clone GitHub..."
    sudo -u "$KIOSK_USER" git clone -b main \
        https://github.com/enzopellegrino/camera-viewer.git \
        "$KIOSK_HOME/camera-viewer"
fi
[ -f "$KIOSK_HOME/camera-viewer/main.py" ] || { echo "ERRORE: app non trovata"; exit 1; }

# ── 5. Python venv ───────────────────────────────────────────────────────────
show_screen "Configurazione in corso..." "Configurazione Python" 60 \
    "✓ Hardware: $GPU_LABEL" \
    "✓ Pacchetti installati" \
    "✓ App installata"
echo "[5/9] Python venv..."
cd "$KIOSK_HOME/camera-viewer"
sudo -H -u "$KIOSK_USER" python3 -m venv .venv
sudo -H -u "$KIOSK_USER" .venv/bin/pip install --upgrade pip -q
sudo -H -u "$KIOSK_USER" .venv/bin/pip install -r requirements.txt -q
sudo -H -u "$KIOSK_USER" .venv/bin/pip install flask -q

# ── 6. Script cv-* ───────────────────────────────────────────────────────────
show_screen "Configurazione in corso..." "Script di sistema" 70 \
    "✓ Hardware: $GPU_LABEL" \
    "✓ Pacchetti installati" \
    "✓ App + Python configurati"
echo "[6/9] Script cv-*..."
install -m 755 raspberry/scripts/cv-mode           /usr/local/sbin/cv-mode
install -m 755 raspberry/scripts/cv-viewer-launch  /usr/local/sbin/cv-viewer-launch
install -m 755 raspberry/scripts/cv-vpn            /usr/local/sbin/cv-vpn
install -m 755 raspberry/scripts/cv-ovpn           /usr/local/sbin/cv-ovpn
install -m 755 raspberry/scripts/cv-ap             /usr/local/sbin/cv-ap
install -m 755 raspberry/scripts/cv-bootmode       /usr/local/sbin/cv-bootmode
install -m 440 raspberry/scripts/sudoers-cv-helpers /etc/sudoers.d/cv-helpers

if [ -n "$CV_HWDEC_BACKEND" ]; then
    sed -i "/export QT_QPA_PLATFORM/a export CV_HWDEC_BACKEND=${CV_HWDEC_BACKEND}\nexport LIBVA_DRIVER_NAME=${LIBVA_DRIVER_NAME}" \
        /usr/local/sbin/cv-viewer-launch
fi

cat > /usr/local/bin/pcmanfm << 'EOF'
#!/bin/bash
if [[ "${1:-}" == "--set-wallpaper" ]]; then
    for arg in "$@"; do [[ "$arg" == --* ]] && continue; feh --bg-fill "$arg" 2>/dev/null || true; break; fi
fi
EOF
chmod +x /usr/local/bin/pcmanfm

# ── 7. Display manager ───────────────────────────────────────────────────────
show_screen "Configurazione in corso..." "Display e kiosk" 80 \
    "✓ Hardware: $GPU_LABEL" \
    "✓ Pacchetti + App installati" \
    "✓ Script di sistema"
echo "[7/9] LightDM + openbox..."
mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/50-autologin.conf << EOF
[Seat:*]
autologin-user=$KIOSK_USER
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
mkdir -p "$KIOSK_HOME/.config/openbox"
cat > "$KIOSK_HOME/.config/openbox/autostart" << 'EOF'
xset s off; xset -dpms; xset s noblank
unclutter -idle 1 -root &
/usr/local/sbin/cv-viewer-launch &
EOF
chown -R "$KIOSK_USER:$KIOSK_USER" "$KIOSK_HOME/.config"
mkdir -p "$KIOSK_HOME/.config/camera-viewer"
chown "$KIOSK_USER:$KIOSK_USER" "$KIOSK_HOME/.config/camera-viewer"
rm -f "$KIOSK_HOME/.Xauthority"
groupadd -f nopasswdlogin
usermod -a -G nopasswdlogin "$KIOSK_USER"
ln -sf /usr/lib/systemd/system/lightdm.service \
       /etc/systemd/system/display-manager.service

# ── 8. Servizi ───────────────────────────────────────────────────────────────
show_screen "Configurazione in corso..." "Attivazione servizi" 90 \
    "✓ Hardware: $GPU_LABEL" \
    "✓ Sistema configurato" \
    "✓ Kiosk pronto"
echo "[8/9] Servizi systemd..."
install -m 644 raspberry/systemd/camera-webconfig.service \
    /etc/systemd/system/camera-webconfig.service
install -m 644 raspberry/systemd/camera-bootmode.service \
    /etc/systemd/system/camera-bootmode.service
# Patch utente kiosk nel servizio webconfig
sed -i "s/KIOSK_USER_PLACEHOLDER/$KIOSK_USER/g" \
    /etc/systemd/system/camera-webconfig.service
systemctl daemon-reload
systemctl enable lightdm
systemctl enable camera-webconfig
systemctl enable camera-bootmode

# ── 9. Fine ──────────────────────────────────────────────────────────────────
echo "[9/9] Completato!"
touch /etc/cv-firstboot.done
rm -f "$KIOSK_HOME/setup-nuc.sh"

IP=$(hostname -I | awk '{print $1}' 2>/dev/null || echo "...")
show_done "$IP"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  ✅ Camera Viewer — Setup completato!        ║"
echo "║  Portal: http://${IP}                ║"
echo "║  Login:  admin / admin               ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "Riavvio in 10 secondi..."
sleep 10
reboot
