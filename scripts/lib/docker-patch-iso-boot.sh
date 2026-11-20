#!/bin/bash
# Fast remaster: GRUB + isolinux menus + splash (+ optional theme). No squashfs rebuild.
set -euo pipefail

IN="${1:?iso in}"
OUT="${2:?iso out}"
STICKLLM="${3:-/stickllm}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq xorriso > /dev/null

tmp=/tmp/stickllm-boot-patch
rm -rf "$tmp"
mkdir -p "$tmp/boot/grub" "$tmp/isolinux"

cp "$STICKLLM/boot/grub.cfg" "$tmp/boot/grub/grub.cfg"
cp "$STICKLLM/boot/grub/theme.txt" "$tmp/boot/grub/theme.txt"
cp "$STICKLLM/boot/grub/splash.png" "$tmp/boot/grub/splash.png"
cp "$STICKLLM/boot/isolinux/live.cfg" "$tmp/isolinux/live.cfg"
cp "$STICKLLM/boot/isolinux/isolinux.cfg" "$tmp/isolinux/isolinux.cfg"
cp "$STICKLLM/boot/isolinux/menu.cfg" "$tmp/isolinux/menu.cfg"
cp "$STICKLLM/boot/isolinux/stdmenu.cfg" "$tmp/isolinux/stdmenu.cfg"
cp "$STICKLLM/boot/isolinux/splash.png" "$tmp/isolinux/splash.png"

find "$tmp" -type f -exec sed -i 's/\r$//' {} +

echo "[stickllm] patching boot menus + splash in ISO…"
xorriso -indev "$IN" -outdev "$OUT" -boot_image any replay \
  -map "$tmp/boot/grub/grub.cfg" /boot/grub/grub.cfg \
  -map "$tmp/boot/grub/theme.txt" /boot/grub/theme.txt \
  -map "$tmp/boot/grub/splash.png" /boot/grub/splash.png \
  -map "$tmp/isolinux/live.cfg" /isolinux/live.cfg \
  -map "$tmp/isolinux/isolinux.cfg" /isolinux/isolinux.cfg \
  -map "$tmp/isolinux/menu.cfg" /isolinux/menu.cfg \
  -map "$tmp/isolinux/stdmenu.cfg" /isolinux/stdmenu.cfg \
  -map "$tmp/isolinux/splash.png" /isolinux/splash.png \
  -chmod 0444 /boot/grub/grub.cfg /isolinux/live.cfg /isolinux/menu.cfg -- \
  -commit

ls -lh "$OUT"
bash "$STICKLLM/scripts/lib/iso-integrity-check.sh" "$OUT"
echo "docker-patch-iso-boot: OK"
