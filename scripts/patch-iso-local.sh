#!/usr/bin/env bash
# Inject StickLLM local console mode + short menus into existing hybrid ISO.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

IN="${1:-out/v0.3.3/stickllm-amd-rtx3090-v0.3.3.hybrid.iso}"
OUT="${2:-out/v0.3.4/stickllm-amd-rtx3090-v0.3.4.hybrid.iso}"
TMP_BASENAME="stickllm-amd-rtx3090.local.iso"
TMP_OUT="out/${TMP_BASENAME}"

export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

test -f "$IN"
test -f boot/grub.cfg
test -f boot/isolinux/live.cfg
test -f overlay/usr/local/bin/stickllm-local-chat
test -f overlay/etc/systemd/system/stickllm-local.service

# Never overwrite a published shipping ISO path by accident.
case "$OUT" in
  out/v0.3.3/*|out/v0.3.2/*|out/v0.3.1/*|out/v0.3.0/*|out/stickllm-amd-rtx3090.hybrid.iso)
    echo "REFUSE: OUT=$OUT would overwrite a shipping artifact" >&2
    exit 1
    ;;
esac

mkdir -p "$(dirname "$OUT")"
# Docker bind is out/ → /host-out; IN may live under out/v0.3.3/
IN_HOST_REL="${IN#out/}"
test -f "out/${IN_HOST_REL}"

VOL="stickllm-iso-local-patch"
docker volume create "$VOL" >/dev/null
docker run --rm --privileged --network host \
  -v "${ROOT}:/stickllm:ro" \
  -v "${ROOT}/out:/host-out" \
  -v "${VOL}:/work" \
  debian:bookworm \
  bash -lc "
    set -e
    cp \"/host-out/${IN_HOST_REL}\" /work/in.iso
    bash /stickllm/scripts/lib/docker-patch-iso-local.sh /work/in.iso /work/out.iso /stickllm
    cp -f /work/out.iso \"/host-out/${TMP_BASENAME}\"
  "

mv -f "$TMP_OUT" "$OUT"
(
  cd "$(dirname "$OUT")"
  sha256sum "$(basename "$OUT")" > SHA256SUMS
)
ls -lh "$OUT"
echo "Patched (local mode): $OUT"
cat "$(dirname "$OUT")/SHA256SUMS"
