#!/bin/bash
# fix-usb-on-nuc.sh
# Usa il NUC (Ubuntu reale) per installare GRUB sulla USB.
# Molto più affidabile di farlo dal Mac via container.
#
# Uso: bash fix-usb-on-nuc.sh [IP_NUC]
set -euo pipefail

NUC_IP="${1:-10.10.70.55}"
NUC_USER="pi"
NUC_PASS="N1computer@2019"
VERSION="2.0"

echo "╔══════════════════════════════════════════════════╗"
echo "║  Fix GRUB USB via NUC (Ubuntu reale x86_64)     ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "NUC: $NUC_IP"
echo ""
echo "1. Inserisci la USB nel NUC (mentre il NUC è acceso e connesso)"
echo "2. Premi Invio quando la USB è inserita"
read -rp "   USB inserita? [Invio]: "

echo ""
echo "→ Cerco la USB sul NUC..."
USB_DEV=$(sshpass -p "$NUC_PASS" ssh -o StrictHostKeyChecking=no "$NUC_USER@$NUC_IP" \
    "lsblk -o NAME,LABEL,SIZE -d | grep -i 'cv-\|camera' | awk '{print \"/dev/\"\$1}' | head -1")

if [ -z "$USB_DEV" ]; then
    echo "USB non trovata automaticamente. Cerco per dimensione..."
    sshpass -p "$NUC_PASS" ssh -o StrictHostKeyChecking=no "$NUC_USER@$NUC_IP" \
        "lsblk -o NAME,SIZE,LABEL,TYPE -d | grep disk"
    echo ""
    read -rp "Inserisci il device USB sul NUC (es. /dev/sdb): " USB_DEV
fi

echo "→ USB: $USB_DEV"
echo ""

sshpass -p "$NUC_PASS" ssh -o StrictHostKeyChecking=no "$NUC_USER@$NUC_IP" \
    "sudo bash -s '$USB_DEV' '$VERSION'" << 'NUCHEOF'
USB_DEV="$1"
VERSION="$2"
set -e

echo "→ Monto le partizioni USB..."
sudo mkdir -p /mnt/usb-fix/boot/efi
sudo mount "${USB_DEV}2" /mnt/usb-fix
sudo mount "${USB_DEV}1" /mnt/usb-fix/boot/efi

# Trova kernel e initrd sull'USB
KERNEL=$(ls /mnt/usb-fix/boot/vmlinuz-*-generic 2>/dev/null | sort -V | tail -1 | sed 's|/mnt/usb-fix||')
INITRD=$(ls /mnt/usb-fix/boot/initrd.img-*-generic 2>/dev/null | sort -V | tail -1 | sed 's|/mnt/usb-fix||')
echo "→ Kernel trovato: $KERNEL"
echo "→ Initrd trovato: $INITRD"

# grub.cfg con kernel reale
cat > /tmp/grub-usb.cfg << CFG
set timeout=8
set default=0
set color_normal=cyan/black
set color_highlight=black/cyan
set menu_color_normal=white/black
set menu_color_highlight=black/cyan

echo "  Camera Viewer v${VERSION}"
echo "  di Enzo Pellegrino"

menuentry " Avvia Camera Viewer" {
    search --no-floppy --label --set=root cv-system
    linux  ${KERNEL} root=LABEL=cv-system rw quiet loglevel=3
    initrd ${INITRD}
}
menuentry " Modalita sicura (nomodeset)" {
    search --no-floppy --label --set=root cv-system
    linux  ${KERNEL} root=LABEL=cv-system rw nomodeset loglevel=3
    initrd ${INITRD}
}
CFG

echo "→ Creo EFI autocontenuto con grub-mkstandalone..."
sudo mkdir -p /mnt/usb-fix/boot/efi/EFI/BOOT
sudo grub-mkstandalone \
    --format=x86_64-efi \
    --output=/mnt/usb-fix/boot/efi/EFI/BOOT/BOOTX64.EFI \
    --modules="part_gpt part_msdos fat ext2 normal boot linux initrd search search_label echo all_video video_fb" \
    --locales="" \
    --fonts="" \
    "boot/grub/grub.cfg=/tmp/grub-usb.cfg"

sudo mkdir -p /mnt/usb-fix/boot/grub
sudo cp /tmp/grub-usb.cfg /mnt/usb-fix/boot/grub/grub.cfg

EFI_SIZE=$(ls -lh /mnt/usb-fix/boot/efi/EFI/BOOT/BOOTX64.EFI | awk '{print $5}')
echo "→ BOOTX64.EFI creato: $EFI_SIZE"

sudo umount /mnt/usb-fix/boot/efi
sudo umount /mnt/usb-fix
echo ""
echo "✅ GRUB installato correttamente sulla USB!"
echo "   Stacca la USB dal NUC e reinseriscila per bootare."
NUCHEOF

echo ""
echo "✅ Fatto! Stacca la USB dal NUC e bootaci sopra."
