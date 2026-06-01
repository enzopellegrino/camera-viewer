#!/bin/bash
# =============================================================================
# Camera Viewer — Build immagine Live USB
# Creato da Enzo Pellegrino
#
# Usa la VM Linux di Podman (non il container) per le operazioni privilegiate.
# La VM ha accesso diretto ai loop device — nessun problema di permessi.
#
# Uso: bash make-image.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="2.0"
OUTPUT_DIR="$SCRIPT_DIR/dist"
OUTPUT_IMG="$OUTPUT_DIR/camera-viewer-v${VERSION}.img.xz"
APP_TGZ="$OUTPUT_DIR/camera-viewer-app.tar.gz"
SETUP_SCRIPT="$SCRIPT_DIR/setup/build_image_inside.sh"

# Colori
R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; C='\033[0;36m'; B='\033[1m'; E='\033[0m'

hdr() {
    clear
    echo -e "${C}${B}"
    echo "  ╔══════════════════════════════════════════════════╗"
    echo "  ║   🎥  Camera Viewer v${VERSION} — Image Builder     ║"
    echo "  ║       Creato da Enzo Pellegrino                 ║"
    echo "  ╚══════════════════════════════════════════════════╝"
    echo -e "${E}"
}

# ── Modalità repair GRUB ──────────────────────────────────────────────────────
# Uso: bash make-image.sh --repair-grub
# Ripara solo il GRUB sull'immagine esistente senza ricostruire tutto.
# Richiede l'immagine compressa in dist/. Durata: ~5 min.
if [[ "${1:-}" == "--repair-grub" ]]; then
    hdr
    echo -e "  ${Y}Modalità REPAIR GRUB${E} — ripara bootloader senza ricostruire l'immagine"
    echo ""
    [ -f "$OUTPUT_IMG" ] || err "Immagine non trovata: $OUTPUT_IMG\n  Esegui prima: bash make-image.sh"

    # Ottieni SSH info VM
    VM_NAME=$(podman machine list --format '{{.Name}}' 2>/dev/null | head -1 | tr -d '* ')
    VM_JSON=$(podman machine inspect "$VM_NAME" 2>/dev/null)
    SSH_PORT=$(echo "$VM_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin)[0]; print(d['SSHConfig']['Port'])")
    SSH_KEY=$(echo "$VM_JSON"  | python3 -c "import json,sys; d=json.load(sys.stdin)[0]; print(d['SSHConfig']['IdentityPath'])")
    SSH_USER=$(echo "$VM_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin)[0]; print(d['SSHConfig']['RemoteUsername'])")
    SSH_OPTS=(-i "$SSH_KEY" -p "$SSH_PORT" -o StrictHostKeyChecking=no -o LogLevel=ERROR)
    SCP_OPTS=(-i "$SSH_KEY" -P "$SSH_PORT" -o StrictHostKeyChecking=no -o LogLevel=ERROR)
    SSH_HOST="${SSH_USER}@localhost"

    echo "[1/4] Preparo directory nella VM e copio immagine..."
    # Assicura che cv-output appartenga all'utente (non root dalla build precedente)
    ssh "${SSH_OPTS[@]}" "$SSH_HOST" \
        "sudo rm -rf \$HOME/cv-output 2>/dev/null; mkdir -p \$HOME/cv-output"
    scp "${SCP_OPTS[@]}" "$OUTPUT_IMG" "${SSH_HOST}:cv-output/"

    echo "[2/4] Decomprimi e ripara GRUB nella VM (via container Ubuntu)..."
    ssh "${SSH_OPTS[@]}" "$SSH_HOST" << REPAIREOF
set -e
sudo modprobe loop max_loop=16 2>/dev/null || true
for i in \$(seq 0 15); do [ -b "/dev/loop\$i" ] || sudo mknod "/dev/loop\$i" b 7 "\$i" 2>/dev/null || true; done
cd \$HOME/cv-output/

IMG_RAW="camera-viewer-v${VERSION}.img"
if [ ! -f "\$IMG_RAW" ]; then
    echo "Decomprimo immagine..."
    xz -d -k camera-viewer-v${VERSION}.img.xz
fi

LOOP=\$(sudo losetup -f --show -P "\$IMG_RAW")
echo "Loop: \$LOOP"
sudo partprobe "\$LOOP" 2>/dev/null || true
sleep 2

# Monta le partizioni per il container
sudo mkdir -p /mnt/cv-repair/boot/efi
sudo mount \${LOOP}p2 /mnt/cv-repair
sudo mkdir -p /mnt/cv-repair/boot/efi
sudo mount \${LOOP}p1 /mnt/cv-repair/boot/efi

# Esegui grub-install DENTRO un container Ubuntu (ha grub-install, Fedora CoreOS no)
sudo podman run --rm --privileged \
    --platform linux/amd64 \
    -v /dev:/dev \
    -v /mnt/cv-repair:/target:z \
    ubuntu:24.04 bash -c "
apt-get update -q && apt-get install -y -q --no-install-recommends grub-efi-amd64-bin grub-pc-bin grub2-common 2>&1 | tail -3

grub-install --target=x86_64-efi \
    --efi-directory=/target/boot/efi \
    --boot-directory=/target/boot \
    --removable --recheck /dev/\$(basename $LOOP) 2>&1 | tail -3

KERNEL=\\\$(ls /target/boot/vmlinuz-*-generic 2>/dev/null | sort -V | tail -1 | sed 's|/target||')
INITRD=\\\$(ls /target/boot/initrd.img-*-generic 2>/dev/null | sort -V | tail -1 | sed 's|/target||')
echo \"Kernel: \\\$KERNEL\"

cat > /target/boot/grub/grub.cfg << 'GRUBCFG'
set timeout=8
set default=0
set color_normal=cyan/black
set color_highlight=black/cyan
set menu_color_normal=white/black
set menu_color_highlight=black/cyan
echo \"  Camera Viewer v${VERSION}\"
echo \"  di Enzo Pellegrino\"
menuentry \" Avvia Camera Viewer\" {
    search --no-floppy --label --set=root cv-system
    linux  \\\${KERNEL} root=LABEL=cv-system rw quiet loglevel=3
    initrd \\\${INITRD}
}
menuentry \" Modalita sicura (nomodeset)\" {
    search --no-floppy --label --set=root cv-system
    linux  \\\${KERNEL} root=LABEL=cv-system rw nomodeset loglevel=3
    initrd \\\${INITRD}
}
GRUBCFG

# grub.cfg anche sulla partizione EFI (GRUB lo cerca li per primo)
mkdir -p /target/boot/efi/EFI/BOOT
cat > /target/boot/efi/EFI/BOOT/grub.cfg << 'EFICFG'
insmod ext2
insmod part_gpt
search --no-floppy --label --set=root cv-system
set prefix=(\\\$root)/boot/grub
source /boot/grub/grub.cfg
EFICFG
echo GRUB_OK
"

sudo umount /mnt/cv-repair/boot/efi 2>/dev/null || true
sudo umount /mnt/cv-repair 2>/dev/null || true
sudo losetup -d "\$LOOP" 2>/dev/null || true
echo "GRUB riparato!"
REPAIREOF

    echo "[3/4] Ricomprimi immagine (veloce, xz -3)..."
    ssh "${SSH_OPTS[@]}" "$SSH_HOST" \
        "cd \$HOME/cv-output/ && rm -f camera-viewer-v${VERSION}.img.xz && XZ_LEVEL=3 xz -3 -T0 camera-viewer-v${VERSION}.img && ls -lh camera-viewer-v${VERSION}.img.xz"

    echo "[4/4] Copia immagine riparata..."
    scp "${SCP_OPTS[@]}" "${SSH_HOST}:cv-output/camera-viewer-v${VERSION}.img.xz" "$OUTPUT_DIR/"
    SIZE=$(ls -lh "$OUTPUT_IMG" | awk '{print $5}')

    echo ""
    echo -e "${G}${B}╔══════════════════════════════════════════════════╗${E}"
    echo -e "${G}${B}║  ✅ GRUB riparato! ($SIZE)                       ║${E}"
    echo -e "${G}${B}║  Scrivi sulla USB: bash make-usb.sh              ║${E}"
    echo -e "${G}${B}╚══════════════════════════════════════════════════╝${E}"
    exit 0
fi

ok()   { echo -e "  ${G}✓${E} $1"; }
warn() { echo -e "  ${Y}⚠${E}  $1"; }
err()  { echo -e "  ${R}✗ ERRORE:${E} $1"; exit 1; }
step() { echo -e "\n${B}[$1/$TOTAL]${E} $2"; }
TOTAL=5

hdr

# ── Step 1: Verifica Podman ───────────────────────────────────────────────────
step 1 "Verifica Podman..."
command -v podman &>/dev/null || err "Podman non trovato"
ok "Podman $(podman --version | awk '{print $3}')"

# Avvia la VM di Podman se non è attiva
VM_STATE=$(podman machine inspect --format '{{.State}}' 2>/dev/null | head -1 || echo "stopped")
if [[ "$VM_STATE" != "running" ]]; then
    echo "  → Avvio VM Podman..."
    podman machine start
    sleep 5
fi
ok "VM Podman attiva"

ok "VM Podman verificata"

# ── Step 2: Prepara archivio app ─────────────────────────────────────────────
step 2 "Creazione archivio app..."
mkdir -p "$OUTPUT_DIR"
cd "$SCRIPT_DIR"
tar czf "$APP_TGZ" \
    --exclude='.git' --exclude='.venv' --exclude='dist' \
    --exclude='build' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='*.spec' --exclude='make-image.sh' --exclude='make-usb.sh' .
ok "App: $(ls -lh "$APP_TGZ" | awk '{print $5}')"

# ── Step 3: Build dentro la VM Podman (loop device disponibili!) ──────────────
step 3 "Copia file nella VM e avvio build (~20-30 min)..."
echo ""

# Ottieni SSH config dalla VM (podman machine scp non disponibile in v5.x)
info() { echo -e "  ${C}→${E} $1"; }
# Strip asterisk (*) dal nome VM — podman lo aggiunge alla VM attiva
VM_NAME=$(podman machine list --format '{{.Name}}' 2>/dev/null | head -1 | tr -d '*' | tr -d ' ')
[ -z "$VM_NAME" ] && VM_NAME="podman-machine-default"
info "VM: $VM_NAME"

VM_JSON=$(podman machine inspect "$VM_NAME" 2>/dev/null) \
    || err "Impossibile ispezionare la VM '$VM_NAME'"

SSH_PORT=$(echo "$VM_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin)[0]; print(d['SSHConfig']['Port'])") \
    || err "SSH port non trovata"
SSH_KEY=$(echo "$VM_JSON"  | python3 -c "import json,sys; d=json.load(sys.stdin)[0]; print(d['SSHConfig']['IdentityPath'])") \
    || err "SSH key non trovata"
SSH_USER=$(echo "$VM_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin)[0]; print(d['SSHConfig']['RemoteUsername'])") \
    || err "SSH user non trovato"
# ssh usa -p minuscola, scp usa -P maiuscola per la porta
SSH_OPTS=(-i "$SSH_KEY" -p "$SSH_PORT" -o StrictHostKeyChecking=no -o LogLevel=ERROR)
SCP_OPTS=(-i "$SSH_KEY" -P "$SSH_PORT" -o StrictHostKeyChecking=no -o LogLevel=ERROR)
SSH_HOST="${SSH_USER}@localhost"

info "SSH: ${SSH_USER}@localhost:${SSH_PORT}"
info "Key: $SSH_KEY"

# Test connessione
ssh "${SSH_OPTS[@]}" "$SSH_HOST" "echo 'SSH OK'" || err "Connessione SSH alla VM fallita"
ok "Connessione SSH alla VM OK"

# Copia file nella VM
info "Copia script e archivio app nella VM..."
# Usa $HOME (non /tmp che potrebbe essere tmpfs limitato in CoreOS)
scp "${SCP_OPTS[@]}" "$SETUP_SCRIPT" "${SSH_HOST}:build_image_inside.sh"
scp "${SCP_OPTS[@]}" "$APP_TGZ"      "${SSH_HOST}:camera-viewer-app.tar.gz"
ok "File copiati nella VM"

info "Avvio container Ubuntu DENTRO la VM (loop device garantiti)..."
echo ""

# La VM è Fedora CoreOS — non ha apt-get.
# Eseguiamo il container Ubuntu DENTRO la VM: lì i container hanno
# accesso diretto ai loop device del kernel Linux reale.
ssh "${SSH_OPTS[@]}" "$SSH_HOST" << SSHEOF
set -e

# Prepara directory
# Usa $HOME (più spazio di /tmp nella VM Fedora CoreOS)
CV_BUILD_DIR="\$HOME/cv-build"
CV_OUT_DIR="\$HOME/cv-output"

mkdir -p "\$CV_BUILD_DIR" "\$CV_OUT_DIR" "\$CV_OUT_DIR/apt-cache"
cp "\$HOME/build_image_inside.sh" "\$CV_BUILD_DIR/"
cp "\$HOME/camera-viewer-app.tar.gz" "\$CV_OUT_DIR/"

echo "→ Spazio disponibile:"
df -h "\$HOME" | tail -1

echo "→ Caricamento modulo loop nella VM..."
sudo modprobe loop max_loop=16 2>/dev/null || true
# Crea loop device se non esistono
for i in \$(seq 0 15); do
    [ -b "/dev/loop\$i" ] || sudo mknod "/dev/loop\$i" b 7 "\$i" 2>/dev/null || true
done
ls /dev/loop0 && echo "loop devices pronti" || echo "warn: loop0 non trovato"

echo "→ Avvio container Ubuntu amd64 con accesso privilegiato..."

# Monta l'intero /dev dalla VM nel container: tutti i loop device disponibili
sudo podman run --rm --privileged \
    --platform linux/amd64 \
    -v /dev:/dev \
    -v "\$CV_BUILD_DIR":/setup:z \
    -v "\$CV_OUT_DIR":/output:z \
    -v "\$CV_OUT_DIR/apt-cache":/var/cache/apt:z \
    ubuntu:24.04 \
    bash /setup/build_image_inside.sh "$VERSION" "/output" "/output/camera-viewer-app.tar.gz"

echo "→ Build completato!"
ls -lh "\$CV_OUT_DIR/"
SSHEOF

# Copia immagine dalla VM al Mac
info "Copia immagine compressa dal Mac..."
mkdir -p "$OUTPUT_DIR"
scp "${SCP_OPTS[@]}" "${SSH_HOST}:cv-output/camera-viewer-v${VERSION}.img.xz" "$OUTPUT_DIR/"

# ── Step 4: Verifica ─────────────────────────────────────────────────────────
step 4 "Verifica output..."
if [ -f "$OUTPUT_IMG" ]; then
    SIZE=$(ls -lh "$OUTPUT_IMG" | awk '{print $5}')
    ok "Immagine: dist/camera-viewer-v${VERSION}.img.xz ($SIZE)"
else
    err "Immagine non trovata: $OUTPUT_IMG"
fi

# ── Step 5: Pulizia ───────────────────────────────────────────────────────────
step 5 "Pulizia file temporanei..."
rm -f "$APP_TGZ"
ok "Pulizia completata"

echo ""
echo -e "${G}${B}╔══════════════════════════════════════════════════╗${E}"
echo -e "${G}${B}║  ✅ Build completato!                            ║${E}"
echo -e "${G}${B}╠══════════════════════════════════════════════════╣${E}"
echo -e "${G}${B}║  File:  dist/camera-viewer-v${VERSION}.img.xz       ║${E}"
echo -e "${G}${B}║  Size:  $SIZE                                    ║${E}"
echo -e "${G}${B}║                                                  ║${E}"
echo -e "${G}${B}║  Per creare una USB:                             ║${E}"
echo -e "${G}${B}║    bash make-usb.sh                              ║${E}"
echo -e "${G}${B}╚══════════════════════════════════════════════════╝${E}"
echo ""
