# Raspberry Pi Camera Viewer — Piano Captive Portal

Sistema di provisioning per Raspberry Pi 4: alla prima accensione il Pi crea un
proprio Access Point WiFi; collegandosi da telefono o PC si apre automaticamente
una pagina web (captive portal) dove si configura la connessione di rete del Pi
e l'elenco delle telecamere RTSP da visualizzare. Una volta configurato e
collegato a un monitor HDMI, il Pi avvia il viewer a schermo intero (kiosk).

---

## 1. Esperienza utente finale

```
1. Accendi il Raspberry (prima volta)
        |
2. Dal telefono vedi la rete WiFi "CameraViewer-Setup" -> ti colleghi
        |
3. Si apre AUTOMATICAMENTE una pagina (captive portal)
        |
4. Nella pagina configuri:
   - Connessione internet del Pi: WiFi (scegli rete + password) o Ethernet
   - Telecamere: nome + URL RTSP + posizione nella griglia
   - Layout e impostazioni viewer
        |
5. Premi "Salva e avvia" -> il Pi si riavvia
        |
6. Colleghi il Pi al monitor HDMI -> parte a schermo intero con le camere
```

Deve esistere un modo per **rientrare in configurazione** dopo il primo setup
(es. flag file su /boot, oppure fallback automatico se la rete non e'
raggiungibile per N secondi).

---

## 2. Componenti tecnici

| # | Componente        | Tecnologia              | Ruolo                                      |
|---|-------------------|-------------------------|--------------------------------------------|
| 1 | Access Point      | hostapd + dnsmasq       | Crea la rete "CameraViewer-Setup"          |
| 2 | Captive Portal    | dnsmasq (DNS hijack) + Flask | Apre la pagina automaticamente        |
| 3 | Web app config    | Flask (Python)          | Pagina configurazione rete + camere        |
| 4 | App Viewer        | PySide6 (esistente)     | Mostra le camere in kiosk fullscreen       |
| 5 | Logica dual-mode  | systemd + script boot   | Decide: provisioning o operativo           |

Tutto in **Python**, per riusare `config_manager`, `license_manager` e il
viewer gia' esistenti.

---

## 3. Logica di avvio (cuore del sistema)

```
        ACCENSIONE
            |
   Esiste config valida + rete raggiungibile?
        |  NO                        |  SI
  MODALITA' PROVISIONING        MODALITA' OPERATIVA
  - Alza Access Point           - Connette a WiFi/Ethernet
  - dnsmasq + captive           - Lancia viewer kiosk
  - Flask serve la pagina       - Mostra le camere
```

**Rientro in config**: file-flag (es. `/boot/setup-mode`) oppure fallback
automatico se la connessione fallisce per N secondi.

---

## 4. Stack e decisioni tecniche

- **OS**: Raspberry Pi OS Bookworm 64-bit (headless al primo setup)
- **Gestione rete**: NetworkManager (default su Bookworm), controllato via `nmcli`
- **Access Point**: hostapd + dnsmasq dedicati durante il provisioning
- **Captive portal**: dnsmasq risolve tutti i domini verso l'IP del Pi; Flask
  risponde ai controlli di connettivita' (iOS/Android/Windows) con redirect
  alla pagina di setup
- **Web app**: Flask (leggero, stesso linguaggio del viewer)
- **Viewer**: codice Python sorgente eseguito direttamente sul Pi
  (NON il bundle PyInstaller, che e' solo Mac/Windows)
- **Display server**: da verificare su Bookworm (Wayland labwc di default su
  Pi4; il viewer PySide6 potrebbe richiedere X11)

---

## 5. Fasi di sviluppo

### FASE 0 — OS pronto (in corso)
- Flash Bookworm 64-bit headless (SSH + WiFi preconfigurati)
- Primo accesso SSH, update sistema

### FASE 1 — Viewer sul Pi (fase a rischio, da affrontare per prima)
- Far girare il codice Python sorgente su ARM64
- Verificare PySide6 + OpenCV su ARM (possibile necessita' di wheel ARM o
  pacchetti apt di sistema)
- Test: mostrare uno stream RTSP a schermo
- Kiosk autostart fullscreen

### FASE 2 — Web app di configurazione (COMPLETATA)
- Flask: pagina rete (scan WiFi via `nmcli`) + CRUD camere
- Legge/scrive lo stesso `config.json` del viewer
- Servizio systemd `camera-webconfig` (porta 8080)
- Endpoint captive-portal detection (iOS/Android/Windows)

### FASE 2bis — VPN WireGuard (split-tunnel)
Alcune telecamere sono raggiungibili solo via VPN. Si configura una VPN
**senza perdere la rete attuale** (split-tunnel): solo le subnet delle camere
remote passano nel tunnel, il resto del traffico resta sulla rete normale.
- Tecnologia: **WireGuard** (kernel nativo + `wireguard-tools`)
- Config: **upload file `.conf`** OPPURE **inserimento manuale** dei campi
- Routing: **split-tunnel** — `AllowedIPs` limitato alle subnet camere
  (mai `0.0.0.0/0`, che farebbe full-tunnel e cambierebbe la default route)
- La web app scrive `/etc/wireguard/wgcam.conf`, attiva con
  `wg-quick up` / `systemctl enable wg-quick@wgcam`
- UI: tab "VPN" con upload/manuale, campo subnet camere, toggle on/off,
  stato handshake
- Permessi: richiede privilegi root (scrittura /etc/wireguard + wg-quick) ->
  il servizio di provisioning girera' come root nelle fasi successive

### FASE 3 — Access Point + Captive Portal
- hostapd + dnsmasq
- Redirect automatico iOS/Android/Windows

### FASE 4 — Dual-mode + systemd
- Script di boot che decide provisioning vs operativo
- Servizi systemd
- Transizione provisioning <-> operativo

### FASE 4bis — Performance viewer: decodifica HARDWARE (per 7-12 camere)
Caso d'uso: 7-12 telecamere simultanee con substream a bassa risoluzione.
La decodifica software (OpenCV/FFmpeg attuale) NON regge 12 stream sul Pi 4.
Soluzione: usare il decoder H.264 hardware del Pi via GStreamer.
- Verificato sul Pi: OpenCV compilato con GStreamer 1.26, `v4l2h264dec` funziona,
  decoder HW presenti (bcm2835-codec-decode /dev/video10-12, rpi-hevc-dec)
- Strategia: in camera_widget._StreamThread, su Linux/Pi usare
  `cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)` con pipeline:
  `rtspsrc location=URL latency=100 protocols=tcp ! rtph264depay ! h264parse !
   v4l2h264dec ! videoconvert ! video/x-raw,format=BGR ! appsink drop=true max-buffers=1`
  Fallback a CAP_FFMPEG (software) su Mac/Windows o se GStreamer non disponibile.
- Usare i SUBSTREAM delle camere (l'utente conferma che le sue li hanno) +
  FPS limitato (gia' configurabile) per ridurre ulteriormente il carico.
- H.265: kernel ha rpi-hevc-dec ma manca l'elemento gstreamer v4l2h265dec
  (servirebbe plugin extra); la maggior parte delle camere usa H.264.

### FASE 4ter — Anteprima camere nel portale (opzionale)
Mostrare le camere anche nel portale web (i browser non leggono RTSP nativo).
- Scelta: anteprima a SNAPSHOT (OpenCV cattura 1 frame, servito come JPEG,
  refresh ogni N secondi) — leggera, utile per verificare la camera in fase setup.
- NON streaming live nel browser (pesante, ridondante col monitor).
- Da decidere se implementarla.

### FASE 5 — Integrazione + test reale
- Flusso completo dalla prima accensione

---

## 6. Punti aperti / rischi

1. **Rischio Fase 1**: sul Pi non si puo' usare l'eseguibile Mac/Win. Serve far
   girare il codice Python. PySide6 su ARM64 puo' richiedere compilazione o
   pacchetti di sistema. Affrontare la Fase 1 per prima.
2. **Connessione internet**: con WiFi, il Pi usa la stessa interfaccia per l'AP
   (in setup) e per connettersi (in operativo) — funziona perche' in momenti
   diversi. Da valutare Ethernet come opzione piu' stabile per RTSP.
3. **Display server Bookworm**: verificare se il viewer Qt gira su Wayland o se
   serve forzare X11 per il kiosk.

---

## 7. Hardware necessario

- Raspberry Pi 4 (4GB+ consigliati)
- SD card 16GB+
- Cavo HDMI + monitor
- Alimentatore USB-C
- Connessione di rete (Ethernet o WiFi)
