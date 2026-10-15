#!/bin/bash
# Remaster hybrid ISO: menus + local chat + SSH + web gateway.
set -euo pipefail

IN="${1:?iso in}"
OUT="${2:?iso out}"
STICKLLM="${3:?stickllm repo root}"

export DEBIAN_FRONTEND=noninteractive
echo "[stickllm] installing patch tools..."
apt-get update -qq
apt-get install -y -qq xorriso squashfs-tools rsync ca-certificates
echo "[stickllm] tools ready"

work=/tmp/stickllm-local-patch
rm -rf "$work"
mkdir -p "$work/iso" "$work/sq" "$work/new"

echo "[stickllm] extracting ISO tree..."
xorriso -osirrox on -indev "$IN" -extract / "$work/iso"

SQ="$work/iso/live/filesystem.squashfs"
test -f "$SQ"

echo "[stickllm] unsquashfs..."
unsquashfs -f -d "$work/sq" "$SQ" >/dev/null
# Drop extracted squashfs copy early — frees ~8GB before overlay/mksquashfs.
rm -f "$SQ"

echo "[stickllm] injecting overlay..."
rsync -a \
  "$STICKLLM/overlay/usr/local/bin/stickllm-bootstatus" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-local-chat" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-console-setup" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-gateway" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-nvidia-prep" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-pick-gpus" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-usb-claim" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-model-probe" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-download-model" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-vault" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-vault-boot" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-persist" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-status" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-pair" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-control" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-lan-ip" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-wifi-apply" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-wifi-setup" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-kiosk" \
  "$STICKLLM/overlay/usr/local/bin/stickllm-llama-start" \
  "$work/sq/usr/local/bin/"
rsync -a \
  "$STICKLLM/overlay/etc/systemd/system/stickllm-bootstatus.service" \
  "$STICKLLM/overlay/etc/systemd/system/stickllm-local.service" \
  "$STICKLLM/overlay/etc/systemd/system/stickllm-kiosk.service" \
  "$STICKLLM/overlay/etc/systemd/system/stickllm-console-setup.service" \
  "$STICKLLM/overlay/etc/systemd/system/stickllm-ssh.service" \
  "$STICKLLM/overlay/etc/systemd/system/stickllm-ui.service" \
  "$STICKLLM/overlay/etc/systemd/system/stickllm-llama.service" \
  "$STICKLLM/overlay/etc/systemd/system/stickllm-nvidia.service" \
  "$STICKLLM/overlay/etc/systemd/system/stickllm-usb.service" \
  "$STICKLLM/overlay/etc/systemd/system/stickllm-control.service" \
  "$work/sq/etc/systemd/system/"
mkdir -p "$work/sq/etc/ssh/sshd_config.d" "$work/sq/opt/stickllm/ui" \
  "$work/sq/etc/modprobe.d" "$work/sq/etc/modules-load.d" "$work/sq/etc/sudoers.d" \
  "$work/sq/etc/stickllm/models" "$work/sq/var/lib/stickllm" "$work/sq/run/stickllm"
rsync -a "$STICKLLM/overlay/etc/ssh/sshd_config.d/stickllm.conf" "$work/sq/etc/ssh/sshd_config.d/"
rsync -a "$STICKLLM/overlay/etc/modprobe.d/stickllm-nvidia-alias.conf" "$work/sq/etc/modprobe.d/"
# Local NVIDIA DRM KMS for Wayland (included in live squashfs / initramfs path via overlay).
if [[ -f "$STICKLLM/overlay/etc/modprobe.d/nvidia-drm.conf" ]]; then
  rsync -a "$STICKLLM/overlay/etc/modprobe.d/nvidia-drm.conf" "$work/sq/etc/modprobe.d/"
fi
if [[ -f "$STICKLLM/overlay/etc/modprobe.d/stickllm-nvidia-drm.conf" ]]; then
  rsync -a "$STICKLLM/overlay/etc/modprobe.d/stickllm-nvidia-drm.conf" "$work/sq/etc/modprobe.d/"
fi
rsync -a "$STICKLLM/overlay/etc/modules-load.d/stickllm-nvidia.conf" "$work/sq/etc/modules-load.d/"
rsync -a "$STICKLLM/overlay/etc/sudoers.d/stickllm" "$work/sq/etc/sudoers.d/stickllm"
rsync -a "$STICKLLM/config/models/catalog.toml" "$work/sq/etc/stickllm/models/catalog.toml"
mkdir -p "$work/sq/etc/stickllm"
if [[ -f "$STICKLLM/overlay/etc/stickllm/default-model.env" ]]; then
  rsync -a "$STICKLLM/overlay/etc/stickllm/default-model.env" "$work/sq/etc/stickllm/default-model.env"
fi
rsync -a "$STICKLLM/ui/" "$work/sq/opt/stickllm/ui/"
if [[ -f "$STICKLLM/overlay/opt/stickllm/ui/stickllm.json" ]]; then
  rsync -a "$STICKLLM/overlay/opt/stickllm/ui/stickllm.json" "$work/sq/opt/stickllm/ui/stickllm.json"
else
  printf '%s\n' '{"mode":"ephemeral","profile":"amd-rtx3090","version":"0.3.4"}' \
    >"$work/sq/opt/stickllm/ui/stickllm.json"
fi

# Strip CRLF from every StickLLM helper (Windows checkout -> exec 127 on shebang).
find "$work/sq/usr/local/bin" -maxdepth 1 -type f -name 'stickllm-*' -exec sed -i 's/\r$//' {} +
sed -i 's/\r$//' \
  "$work/sq/etc/systemd/system/"stickllm-*.service \
  "$work/sq/etc/ssh/sshd_config.d/stickllm.conf" \
  "$work/sq/etc/modprobe.d/stickllm-nvidia-alias.conf" \
  "$work/sq/etc/modules-load.d/stickllm-nvidia.conf" \
  "$work/sq/etc/sudoers.d/stickllm" \
  "$work/sq/etc/stickllm/models/catalog.toml" \
  "$work/sq/etc/stickllm/default-model.env" \
  "$work/sq/opt/stickllm/ui/"*.js \
  "$work/sq/opt/stickllm/ui/"*.html \
  "$work/sq/opt/stickllm/ui/"*.css \
  "$work/sq/opt/stickllm/ui/stickllm.json" 2>/dev/null || true
find "$work/sq/usr/local/bin" -maxdepth 1 -type f -name 'stickllm-*' -exec chmod 755 {} +
chmod 644 "$work/sq/etc/systemd/system/"stickllm-*.service
chmod 644 "$work/sq/etc/ssh/sshd_config.d/stickllm.conf"
chmod 644 "$work/sq/etc/modprobe.d/stickllm-nvidia-alias.conf"
chmod 644 "$work/sq/etc/modprobe.d/nvidia-drm.conf" 2>/dev/null || true
chmod 644 "$work/sq/etc/modprobe.d/stickllm-nvidia-drm.conf" 2>/dev/null || true
chmod 644 "$work/sq/etc/modules-load.d/stickllm-nvidia.conf"
chmod 644 "$work/sq/etc/stickllm/models/catalog.toml"
chmod 440 "$work/sq/etc/sudoers.d/stickllm"

mkdir -p "$work/sq/etc/systemd/system/multi-user.target.wants"
for u in stickllm-console-setup stickllm-usb stickllm-control stickllm-nvidia stickllm-bootstatus stickllm-local stickllm-ssh stickllm-ui stickllm-llama; do
  ln -sfn "/etc/systemd/system/${u}.service" \
    "$work/sq/etc/systemd/system/multi-user.target.wants/${u}.service"
done

echo "[stickllm] ensuring openssh-server in squashfs..."
mkdir -p "$work/sq/dev" "$work/sq/proc" "$work/sq/sys" "$work/sq/run" "$work/sq/dev/pts"
mount --bind /dev "$work/sq/dev"
mount -t devpts devpts "$work/sq/dev/pts" || true
mount -t proc proc "$work/sq/proc"
mount -t sysfs sys "$work/sq/sys"
mount -t tmpfs tmpfs "$work/sq/run"
cp /etc/resolv.conf "$work/sq/etc/resolv.conf"
chroot "$work/sq" /bin/bash -c "set -e; export DEBIAN_FRONTEND=noninteractive; apt-get update -qq; apt-get install -y -qq openssh-server openssh-sftp-server parted e2fsprogs; systemctl disable ssh.service 2>/dev/null || true; systemctl disable sshd.service 2>/dev/null || true; rm -f /etc/systemd/system/multi-user.target.wants/ssh.service"
umount "$work/sq/dev/pts" 2>/dev/null || true
umount "$work/sq/run" "$work/sq/sys" "$work/sq/proc" "$work/sq/dev"

echo "[stickllm] rewriting boot menus..."
mkdir -p "$work/iso/boot/grub" "$work/iso/isolinux"
tr -d '\r' < "$STICKLLM/boot/grub.cfg" > "$work/iso/boot/grub/grub.cfg"
tr -d '\r' < "$STICKLLM/boot/isolinux/live.cfg" > "$work/iso/isolinux/live.cfg"
tr -d '\r' < "$STICKLLM/boot/isolinux/isolinux.cfg" > "$work/iso/isolinux/isolinux.cfg"
tr -d '\r' < "$STICKLLM/boot/isolinux/menu.cfg" > "$work/iso/isolinux/menu.cfg"
tr -d '\r' < "$STICKLLM/boot/isolinux/stdmenu.cfg" > "$work/iso/isolinux/stdmenu.cfg"
if [[ -f "$STICKLLM/boot/grub/theme.txt" ]]; then
  tr -d '\r' < "$STICKLLM/boot/grub/theme.txt" > "$work/iso/boot/grub/theme.txt"
fi
if [[ -f "$STICKLLM/boot/isolinux/splash.png" ]]; then
  cp -f "$STICKLLM/boot/isolinux/splash.png" "$work/iso/isolinux/splash.png"
  cp -f "$STICKLLM/boot/isolinux/splash.png" "$work/iso/boot/grub/splash.png"
fi

echo "[stickllm] mksquashfs..."
rm -f "$work/new/filesystem.squashfs"
mksquashfs "$work/sq" "$work/new/filesystem.squashfs" -comp xz -b 1M -Xdict-size 100% -noappend >/dev/null
rm -rf "$work/sq"
mkdir -p "$work/iso/live"
cp -f "$work/new/filesystem.squashfs" "$work/iso/live/filesystem.squashfs"
rm -f "$work/new/filesystem.squashfs"

echo "[stickllm] rebuilding hybrid ISO..."
rm -f "$OUT"
XORRISO_ARGS=(
  -indev "$IN"
  -outdev "$OUT"
  -boot_image any replay
  -map "$work/iso/boot/grub/grub.cfg" /boot/grub/grub.cfg
  -map "$work/iso/isolinux/live.cfg" /isolinux/live.cfg
  -map "$work/iso/isolinux/isolinux.cfg" /isolinux/isolinux.cfg
  -map "$work/iso/isolinux/menu.cfg" /isolinux/menu.cfg
  -map "$work/iso/isolinux/stdmenu.cfg" /isolinux/stdmenu.cfg
  -map "$work/iso/live/filesystem.squashfs" /live/filesystem.squashfs
)
if [[ -f "$work/iso/boot/grub/theme.txt" ]]; then
  XORRISO_ARGS+=(-map "$work/iso/boot/grub/theme.txt" /boot/grub/theme.txt)
fi
if [[ -f "$work/iso/isolinux/splash.png" ]]; then
  XORRISO_ARGS+=(-map "$work/iso/isolinux/splash.png" /isolinux/splash.png)
  XORRISO_ARGS+=(-map "$work/iso/boot/grub/splash.png" /boot/grub/splash.png)
fi
XORRISO_ARGS+=(-chmod 0444 /boot/grub/grub.cfg /isolinux/live.cfg /isolinux/menu.cfg -- -commit)
xorriso "${XORRISO_ARGS[@]}"

ls -lh "$OUT"
# Catch OneDrive/NTFS / interrupted copies that leave GRUB-only truncated hybrids.
bash "$STICKLLM/scripts/lib/iso-integrity-check.sh" "$OUT"
echo "docker-patch-iso-local: OK"
