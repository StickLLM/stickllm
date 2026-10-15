#!/usr/bin/env bash
# Inject StickLLM local console mode + short menus into existing hybrid ISO.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Defaults target the next unshipped line (new naming). Pass args to override.
# Historical ships keep stickllm-amd-rtx3090-v*.hybrid.iso — never write those.
IN="${1:-out/v0.3.6/stickllm-amd-rtx3090-v0.3.6.hybrid.iso}"
OUT="${2:-out/v0.3.7/StickLLM-v0.3.7.iso}"
TMP_BASENAME="StickLLM.local.iso"
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
  out/v0.3.6/*|out/v0.3.5/*|out/v0.3.4/*|out/v0.3.3/*|out/v0.3.2/*|out/v0.3.1/*|out/v0.3.0/*|out/stickllm-amd-rtx3090.hybrid.iso|out/stickllm-amd-rtx3090-v0.2.hybrid.iso|out/stickllm-amd-rtx3090-v0.3.6.hybrid.iso)
    echo "REFUSE: OUT=$OUT would overwrite a shipping artifact" >&2
    exit 1
    ;;
esac

mkdir -p "$(dirname "$OUT")"
# Docker bind is out/ → /host-out; IN may live under out/v0.3.3/
IN_HOST_REL="${IN#out/}"
test -f "out/${IN_HOST_REL}"
OUT_REL="${OUT#out/}"
OUT_DIR=$(dirname "$OUT_REL")
OUT_BASE=$(basename "$OUT_REL")

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
    bash /stickllm/scripts/lib/iso-integrity-check.sh /work/out.iso
    cp -f /work/out.iso \"/host-out/${TMP_BASENAME}\"
    bash /stickllm/scripts/lib/iso-integrity-check.sh \"/host-out/${TMP_BASENAME}\"
  "

mv -f "$TMP_OUT" "$OUT"

docker run --rm \
  -v "${ROOT}:/stickllm:ro" \
  -v "${ROOT}/out:/host-out" \
  debian:bookworm \
  bash -lc "
    set -e
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq xorriso >/dev/null
    bash /stickllm/scripts/lib/iso-integrity-check.sh /host-out/${OUT_REL}
    cd /host-out/${OUT_DIR}
    sha256sum '${OUT_BASE}' | tee SHA256SUMS
  "

# Mirror checksum beside other release digests when OUT is a versioned path.
if [[ "$OUT_DIR" == v0.* ]]; then
  cp -f "$(dirname "$OUT")/SHA256SUMS" "$ROOT/checksums/${OUT_DIR}.sha256"
fi
ls -lh "$OUT"
echo "Patched (local mode): $OUT"
cat "$(dirname "$OUT")/SHA256SUMS"
