#!/usr/bin/env bash
# Fast path: rewrite GRUB inside existing hybrid ISO (minutes, not an hour).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Prefer explicit args. Defaults avoid clobbering Drive golden / shipped names.
IN="${1:-out/StickLLM-v0.3.7.iso}"
OUT="${2:-out/StickLLM-v0.3.7.iso}"
TMP_OUT="out/StickLLM.patched.iso"

export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

test -f "$IN"
test -f boot/grub.cfg

# Write patched ISO inside a Docker named volume first (OneDrive/NTFS bind mounts
# truncate xorriso output). Then copy the finished file to out/.
VOL="stickllm-iso-patch"
docker volume create "$VOL" >/dev/null
docker run --rm \
  -v "${ROOT}:/stickllm:ro" \
  -v "${ROOT}/out:/host-out" \
  -v "${VOL}:/work" \
  debian:bookworm \
  bash -lc "
    set -e
    cp /host-out/$(basename "$IN") /work/in.iso
    bash /stickllm/scripts/lib/docker-patch-iso-boot.sh /work/in.iso /work/out.iso /stickllm
    cp -f /work/out.iso /host-out/$(basename "$TMP_OUT")
  "

mv -f "$TMP_OUT" "$OUT"
ls -lh "$OUT"
echo "Patched: $OUT"
