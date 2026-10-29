#!/bin/bash
# Runs inside debian:bookworm.
# /stickllm = repo (ro), /work = Linux filesystem volume (rw) for live-build.
set -euo pipefail

MODEL_3B="qwen2.5-3b-instruct-q4_k_m.gguf"
# ISO bake is the 3B only. The 7B Q5 stays a catalog download (ISS-020).

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  live-build live-boot live-config live-config-systemd \
  ca-certificates curl rsync xz-utils \
  squashfs-tools xorriso isolinux syslinux-common \
  grub-pc-bin grub-efi-amd64-bin mtools dosfstools \
  build-essential cmake pkg-config python3 git

cd /work
rm -rf /work/*
lb clean --purge || true

MIRROR="${STICKLLM_DEBIAN_MIRROR:-http://deb.debian.org/debian/}"
SEC_MIRROR="${STICKLLM_DEBIAN_SECURITY_MIRROR:-http://security.debian.org/debian-security/}"

lb config \
  --architectures amd64 \
  --distribution bookworm \
  --archive-areas "main contrib non-free non-free-firmware" \
  --parent-archive-areas "main contrib non-free non-free-firmware" \
  --mirror-bootstrap "$MIRROR" \
  --mirror-chroot "$MIRROR" \
  --mirror-binary "$MIRROR" \
  --parent-mirror-bootstrap "$MIRROR" \
  --parent-mirror-chroot "$MIRROR" \
  --parent-mirror-binary "$MIRROR" \
  --mirror-chroot-security "$SEC_MIRROR" \
  --mirror-binary-security "$SEC_MIRROR" \
  --parent-mirror-chroot-security "$SEC_MIRROR" \
  --parent-mirror-binary-security "$SEC_MIRROR" \
  --binary-images iso-hybrid \
  --bootloaders "grub-efi,syslinux" \
  --debian-installer none \
  --apt-recommends false \
  --apt-indices true \
  --firmware-binary true \
  --firmware-chroot true \
  --memtest none \
  --iso-application "StickLLM" \
  --iso-volume "STICKLLM" \
  --iso-publisher "Nink Inc." \
  --linux-packages "linux-image linux-headers" \
  --chroot-squashfs-compression-type xz

echo "[stickllm] mirrors: $MIRROR / $SEC_MIRROR"
cat config/archives/*.list.chroot 2>/dev/null || true

mkdir -p config/package-lists
# Honor tracked package list (ISS-010) — strip CRLF from Windows checkouts.
if [[ -f /stickllm/live-build/package-lists/stickllm.list.chroot ]]; then
  tr -d '\r' < /stickllm/live-build/package-lists/stickllm.list.chroot \
    > config/package-lists/stickllm.list.chroot
else
  echo "ERROR: missing /stickllm/live-build/package-lists/stickllm.list.chroot" >&2
  exit 1
fi
grep -q '^docker.io$' config/package-lists/stickllm.list.chroot
grep -q '^chromium$' config/package-lists/stickllm.list.chroot
grep -q '^cage$' config/package-lists/stickllm.list.chroot
grep -q '^seatd$' config/package-lists/stickllm.list.chroot

mkdir -p config/hooks/normal
for h in /stickllm/live-build/hooks/normal/*.hook.chroot; do
  base="$(basename "$h")"
  tr -d '\r' < "$h" > "config/hooks/normal/$base"
  chmod +x "config/hooks/normal/$base"
done

# Overlay into includes.chroot (after lb config created the tree)
mkdir -p config/includes.chroot
rsync -a /stickllm/overlay/ config/includes.chroot/
# systemd rejects unit files marked executable (common on Windows mounts)
# Drop-ins (*.conf), timers and sockets too: systemd warns "marked executable".
find config/includes.chroot/etc/systemd -type f \( -name '*.service' -o -name '*.conf' -o -name '*.timer' -o -name '*.socket' -o -name '*.target' \) -exec chmod 644 {} +
find config/includes.chroot/usr/local/bin -type f -exec chmod 755 {} +
find config/includes.chroot/etc/sudoers.d -type f -exec chmod 440 {} +

mkdir -p config/includes.chroot/opt/stickllm/ui
rsync -a /stickllm/ui/ config/includes.chroot/opt/stickllm/ui/

mkdir -p config/includes.chroot/opt/stickllm/models
cp "/stickllm/models/${MODEL_3B}" config/includes.chroot/opt/stickllm/models/

mkdir -p config/includes.chroot/etc/stickllm config/includes.chroot/etc/stickllm/models
cp /stickllm/config/profiles/amd-rtx3090.toml config/includes.chroot/etc/stickllm/profile.toml
cp /stickllm/config/models/catalog.toml config/includes.chroot/etc/stickllm/models/catalog.toml

test -x config/includes.chroot/opt/stickllm/bin/llama-server
test -x config/includes.chroot/opt/stickllm/bin/llama-server-cpu
test -f config/includes.chroot/opt/stickllm/lib/libllama-server-impl.so
test -f "config/includes.chroot/opt/stickllm/models/${MODEL_3B}"
if compgen -G "config/includes.chroot/opt/stickllm/models/*7b*" >/dev/null; then
  echo "ERROR: 7B GGUF must not be baked into the ISO" >&2
  exit 1
fi

# Voice weights live in /opt/stickllm/speech (a normal folder). Not the SSD vault.
echo "[stickllm] bake speech (whisper.cpp CPU + KittenTTS mini 0.8)…"
bash /stickllm/scripts/lib/bake-speech.sh /work
test -x config/includes.chroot/usr/local/bin/whisper-cli
test -x config/includes.chroot/usr/local/bin/whisper-server
test -f config/includes.chroot/opt/stickllm/speech/ggml-tiny.en.bin
test -f config/includes.chroot/opt/stickllm/speech/kitten_tts_mini_v0_8.onnx
test -f config/includes.chroot/opt/stickllm/speech/voices.npz
test -f config/includes.chroot/opt/stickllm/speech/py/onnxruntime/__init__.py
test -x config/includes.chroot/usr/local/bin/stickllm-usb-claim
test -x config/includes.chroot/usr/local/bin/stickllm-usb-settings
test -f config/includes.chroot/usr/local/lib/stickllm_usb_settings.py
if find config/includes.chroot -path '*vault*' \( -name 'ggml-tiny.en.bin' -o -name 'kitten_tts_mini_v0_8.onnx' -o -name 'voices.npz' \) | grep -q .; then
  echo "ERROR: voice weights must not be inside the vault" >&2
  exit 1
fi
test -x config/includes.chroot/usr/local/bin/stickllm-kiosk
test -f config/includes.chroot/etc/systemd/system/stickllm-kiosk.service
grep -q 'base_model_id = "qwen25-3b-q4km"' config/includes.chroot/etc/stickllm/models/catalog.toml
grep -q 'stickllm-llama-start' config/includes.chroot/etc/systemd/system/stickllm-llama.service
grep -q 'STICKLLM_LLAMA_HOST=127.0.0.1' config/includes.chroot/etc/systemd/system/stickllm-llama.service
test -f config/includes.chroot/usr/local/share/stickllm/agent-zero.pin
grep -q 'amd64_digest=sha256:307a2ceffc8501ba05a1e7253e8b6e4d656d2e1c3b97f0eb943c18b9c40a30fd' \
  config/includes.chroot/usr/local/share/stickllm/agent-zero.pin
test -f config/includes.chroot/usr/local/bin/stickllm-agent
test -f config/includes.chroot/etc/systemd/system/stickllm-agent.service
test -f config/includes.chroot/etc/systemd/system/stickllm-agent-install.service
test -f config/includes.chroot/usr/local/bin/stickllm-dockerd
test -f config/includes.chroot/etc/systemd/system/stickllm-dockerd.service
test -f config/includes.chroot/usr/local/bin/stickllm-docs
test -f config/includes.chroot/usr/local/bin/stickllm-docs-entrypoint
test -f config/includes.chroot/usr/local/lib/stickllm_docs.py
test -f config/includes.chroot/etc/systemd/system/stickllm-docs.service
test -f config/includes.chroot/etc/systemd/system/stickllm-docs-install.service
test -f config/includes.chroot/usr/local/share/stickllm/onlyoffice.pin
grep -q 'amd64_digest=sha256:bff1a9fd46f2b79ada776fd0447c3fccf66cbf44c1996ec9316efa8ac4ee3fd5' \
  config/includes.chroot/usr/local/share/stickllm/onlyoffice.pin
# Starter add-ons (Tasks.md, Paisa, Trilium, Node-RED, ComfyUI).
test -f config/includes.chroot/usr/local/bin/stickllm-addon
test -f config/includes.chroot/usr/local/lib/stickllm_addons.py
test -f config/includes.chroot/etc/systemd/system/stickllm-addon@.service
test -f config/includes.chroot/etc/systemd/system/stickllm-addon-install@.service
test -f config/includes.chroot/usr/local/share/stickllm/addons/node-red-settings.js
for pin in tasks-md paisa trilium node-red comfyui; do
  grep -q '^amd64_digest=sha256:' "config/includes.chroot/usr/local/share/stickllm/addons/${pin}.pin"
done
# Verified list (apps, plugins, models): the shipped verified.json must match
# the pins, the plugin allowlist and the model catalog, or the build stops.
test -f config/includes.chroot/usr/local/share/stickllm/verified.json
test -f config/includes.chroot/usr/local/lib/stickllm_verify.py
python3 -B /stickllm/scripts/pins.py verify

# Agent Zero plugins: none at all since v0.5.4. The allowlist must stay empty
# (any entry stops the build); bake still runs so the image gets an empty
# MANIFEST and the runtime has nothing to load. Never fetched at runtime.
A0_PLUGINS_OUT=config/includes.chroot/usr/local/share/stickllm/agent-zero-plugins
test -f config/includes.chroot/usr/local/share/stickllm/agent-zero-plugins.allow
if [ -n "$(python3 /stickllm/scripts/lib/a0_plugins.py check config/includes.chroot/usr/local/share/stickllm/agent-zero-plugins.allow)" ]; then
  echo "Agent Zero plugins are not allowed (v0.5.4): agent-zero-plugins.allow must be empty" >&2
  exit 1
fi
python3 /stickllm/scripts/lib/a0_plugins.py bake \
  config/includes.chroot/usr/local/share/stickllm/agent-zero-plugins.allow \
  "$A0_PLUGINS_OUT"
chown -R root:root "$A0_PLUGINS_OUT"
test -f "$A0_PLUGINS_OUT/MANIFEST"
test ! -s "$A0_PLUGINS_OUT/MANIFEST"

mkdir -p config/bootloaders/grub-pc config/bootloaders/grub-efi
# Prefer tracked boot/grub.cfg (LF). Fall back to inline copy if missing.
if [[ -f /stickllm/boot/grub.cfg ]]; then
  tr -d '\r' < /stickllm/boot/grub.cfg > config/bootloaders/grub-efi/grub.cfg
else
  cp /dev/null config/bootloaders/grub-efi/grub.cfg
fi
cp config/bootloaders/grub-efi/grub.cfg config/bootloaders/grub-pc/grub.cfg

# BIOS/legacy hosts (like .70 / ROMED8) use isolinux — not our GRUB file.
# live-build generates isolinux; overwrite after lb config via includes.binary.
mkdir -p config/includes.binary/isolinux config/includes.binary/boot/grub
for f in live.cfg isolinux.cfg menu.cfg stdmenu.cfg; do
  if [[ -f "/stickllm/boot/isolinux/${f}" ]]; then
    tr -d '\r' < "/stickllm/boot/isolinux/${f}" > "config/includes.binary/isolinux/${f}"
  fi
done
if [[ -f /stickllm/boot/isolinux/splash.png ]]; then
  cp -f /stickllm/boot/isolinux/splash.png config/includes.binary/isolinux/splash.png
  cp -f /stickllm/boot/isolinux/splash.png config/includes.binary/boot/grub/splash.png
fi
if [[ -f /stickllm/boot/grub.cfg ]]; then
  tr -d '\r' < /stickllm/boot/grub.cfg > config/includes.binary/boot/grub/grub.cfg
fi
# GRUB theme (ISS-019): visible selected_item_color; no empty pixmap_style.
if [[ -f /stickllm/boot/grub/theme.txt ]]; then
  tr -d '\r' < /stickllm/boot/grub/theme.txt > config/includes.binary/boot/grub/theme.txt
fi
if [[ -f /stickllm/boot/grub/splash.png ]]; then
  cp -f /stickllm/boot/grub/splash.png config/includes.binary/boot/grub/splash.png
fi

# Docker Desktop: sync(2) walks every VM superblock and can block forever in
# fuse_sync_fs on the Windows file share. debootstrap calls sync after the
# base system is unpacked. Flush only the live-build volume.
if [[ -x /bin/sync && ! -e /bin/sync.real ]]; then
  mv /bin/sync /bin/sync.real
fi
cat > /bin/sync << 'EOF'
#!/bin/sh
# Sync the live-build volume only. A global sync(2) hangs on Docker Desktop.
if [ -x /bin/sync.real ]; then
  /bin/sync.real -f /work >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 755 /bin/sync

echo "[stickllm] lb build (long)…"
lb build

mkdir -p /stickllm-out
shopt -s nullglob
for f in /work/*.hybrid.iso /work/*.iso; do
  # Verify on the Docker volume first (source of truth).
  bash /stickllm/scripts/lib/iso-integrity-check.sh "$f"
  cp -f "$f" "/stickllm-out/$(basename "$f")"
  # OneDrive/NTFS bind mounts have truncated hybrids before — fail loud.
  bash /stickllm/scripts/lib/iso-integrity-check.sh "/stickllm-out/$(basename "$f")"
  ls -lh "$f" "/stickllm-out/$(basename "$f")"
done
echo "docker-build-live: OK"
