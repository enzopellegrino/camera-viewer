#!/bin/bash
# =============================================================================
# Camera Viewer — WiFi Hotspot Fallback
#
# Se al boot non c'è rete attiva (né ethernet né WiFi configurato),
# crea un access point WiFi così l'utente può connettersi e accedere
# al portale di configurazione su http://10.42.0.1
#
# SSID:     CameraViewer-XXXX  (XXXX = ultime 4 cifre del MAC WiFi)
# Password: cameraviewer
# =============================================================================
LOG="/var/log/cv-hotspot.log"
exec >> "$LOG" 2>&1
echo "$(date '+%F %T') — cv-hotspot avviato"

# Aspetta che NetworkManager sia completamente pronto
sleep 12

# Se c'è già una connessione attiva (ethernet o WiFi), non serve hotspot
CONNECTED=$(nmcli -t -f TYPE,STATE connection show --active 2>/dev/null \
    | grep -v "^loopback:" | grep ":activated" | head -1)
if [ -n "$CONNECTED" ]; then
    echo "$(date '+%F %T') — Rete attiva ($CONNECTED), hotspot non necessario"
    exit 0
fi

# Trova interfaccia WiFi
WIFI_IF=$(nmcli -t -f DEVICE,TYPE device status 2>/dev/null \
    | grep ":wifi" | cut -d: -f1 | head -1)
if [ -z "$WIFI_IF" ]; then
    echo "$(date '+%F %T') — Nessuna interfaccia WiFi trovata"
    exit 1
fi

# SSID basato sulle ultime 4 cifre del MAC (es. CameraViewer-A3F2)
MAC=$(cat /sys/class/net/"$WIFI_IF"/address 2>/dev/null | tr -d ':')
SUFFIX=$(echo "${MAC: -4}" | tr '[:lower:]' '[:upper:]')
SSID="CameraViewer-${SUFFIX}"
PASSWORD="cameraviewer"

echo "$(date '+%F %T') — Avvio hotspot: SSID=$SSID su $WIFI_IF"
nmcli connection delete "cv-hotspot" 2>/dev/null || true

nmcli device wifi hotspot \
    ifname "$WIFI_IF" \
    ssid "$SSID" \
    password "$PASSWORD" \
    con-name "cv-hotspot"

if [ $? -eq 0 ]; then
    # NetworkManager usa 10.42.0.1 come IP default per hotspot
    IP=$(ip -4 addr show "$WIFI_IF" 2>/dev/null \
        | grep -oP '(?<=inet )\d+\.\d+\.\d+\.\d+' | head -1)
    IP="${IP:-10.42.0.1}"
    echo "$(date '+%F %T') — Hotspot attivo: SSID=$SSID PASSWORD=$PASSWORD IP=$IP"

    # Salva info in JSON per il kiosk (può mostrare SSID/IP sullo schermo)
    printf '{"ssid":"%s","password":"%s","ip":"%s","portal":"http://%s"}\n' \
        "$SSID" "$PASSWORD" "$IP" "$IP" \
        > /run/cv-network-info.json
else
    echo "$(date '+%F %T') — Errore avvio hotspot"
    exit 1
fi
