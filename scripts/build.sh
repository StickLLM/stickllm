#!/usr/bin/env bash
# Reproducible StickLLM live ISO build (Debian live-build in Docker).
# Host profile toml: amd-rtx3090 (hardware defaults; not part of ISO filename).
#
# ISO naming (v0.3.7+): StickLLM-vX.Y.Z.iso  (exact; no .hybrid / no profile)
# Through v0.3.6 ships used stickllm-amd-rtx3090-v*.hybrid.iso — leave those alone.
#
# Important on Windows: live-build/debootstrap must run on a Docker named
# volume (Linux fs). Building directly on a OneDrive/NTFS bind mount fails
# with "Tried to extract package, but file already exists".
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROFILE="amd-rtx3090"
# Next unshipped line. Override: STICKLLM_VERSION=0.4.0 ./scripts/build.sh
# Never point this at a published ship (v0.2.0 / v0.3.0 / v0.3.6 / v0.3.8).
VERSION="${STICKLLM_VERSION:-0.3.9}"
VERSION_DIR="v${VERSION}"
ISO_NAME="StickLLM-v${VERSION}.iso"
CHECKSUM_FILE="checksums/v${VERSION}.sha256"
MODEL_3B="qwen2.5-3b-instruct-q4_k_m.gguf"
# TODO(post-v0.3.8 / ISS-020): stop requiring/baking 7B shards; keep 3B only on ISO.
MODEL_SHARD1="qwen2.5-7b-instruct-q5_k_m-00001-of-00002.gguf"
MODEL_SHARD2="qwen2.5-7b-instruct-q5_k_m-00002-of-00002.gguf"
VOL_WORK="stickllm-lb-work"

case "$VERSION_DIR" in
  v0.2.0|v0.2.1-local-nvidia-kbd|v0.3.0|v0.3.1|v0.3.2|v0.3.3|v0.3.4|v0.3.5|v0.3.6|v0.3.7|v0.3.8)
    echo "REFUSE: VERSION=${VERSION} would overwrite a shipping artifact" >&2
    exit 1
    ;;
esac

echo "=== StickLLM build (${ISO_NAME}) ==="
./scripts/verify-host.sh

if [[ ! -f "models/${MODEL_3B}" || ! -f "models/${MODEL_SHARD1}" || ! -f "models/${MODEL_SHARD2}" ]]; then
  echo "Model GGUFs missing — fetching (3B default + 7B)…"
  ./scripts/download-model.sh
fi

./scripts/build-llama-server.sh

mkdir -p out

# Git Bash on Windows rewrites Unix-style Docker paths; disable conversion.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

docker volume create "$VOL_WORK" >/dev/null

echo "Assembling live-build tree on Docker volume ${VOL_WORK}…"

docker run --rm --privileged --network host \
  -e "STICKLLM_DEBIAN_MIRROR=${STICKLLM_DEBIAN_MIRROR:-}" \
  -e "STICKLLM_DEBIAN_SECURITY_MIRROR=${STICKLLM_DEBIAN_SECURITY_MIRROR:-}" \
  -v "${ROOT}:/stickllm:ro" \
  -v "${ROOT}/out:/stickllm-out" \
  -v "${VOL_WORK}:/work" \
  -w //work \
  debian:bookworm \
  bash //stickllm/scripts/lib/docker-build-live.sh

mkdir -p "out/${VERSION_DIR}"
# Prefer hybrid iso freshly written by docker-build-live into out/
SRC_ISO=""
if [[ -f "out/${ISO_NAME}" ]]; then
  SRC_ISO="out/${ISO_NAME}"
elif compgen -G "out/live-image-amd64.hybrid.iso" >/dev/null; then
  SRC_ISO="out/live-image-amd64.hybrid.iso"
elif compgen -G "out/*.hybrid.iso" >/dev/null; then
  shopt -s nullglob
  for f in out/*.hybrid.iso; do
    # Never treat a published shipping ISO name as the new build artifact.
    case "$(basename "$f")" in
      stickllm-amd-rtx3090.hybrid.iso|stickllm-amd-rtx3090-v0.2.hybrid.iso|stickllm-amd-rtx3090-v0.3.6.hybrid.iso)
        continue
        ;;
    esac
    SRC_ISO="$f"
    break
  done
fi
if [[ -z "$SRC_ISO" || ! -f "$SRC_ISO" ]]; then
  echo "ERROR: no new ISO in out/"
  ls -la out/ || true
  exit 1
fi
cp -f "$SRC_ISO" "out/${VERSION_DIR}/${ISO_NAME}"
# Also leave a copy at out/${ISO_NAME} for scripts that look there (not a shipping name).
cp -f "$SRC_ISO" "out/${ISO_NAME}"
(
  cd "out/${VERSION_DIR}"
  sha256sum "${ISO_NAME}" > "SHA256SUMS"
)
cp -f "out/${VERSION_DIR}/SHA256SUMS" "$CHECKSUM_FILE"

ls -lh "out/${VERSION_DIR}/${ISO_NAME}"
echo "=== Build complete: out/${VERSION_DIR}/${ISO_NAME} ==="
echo "Checksum: ${CHECKSUM_FILE}"
echo "Flash: docs/FLASH.md (Rufus DD on Windows, or dd on Linux)"
echo "Note: does not overwrite checksums/v0.3.6.sha256 or Drive golden; Naming: StickLLM-vX.Y.Z.iso"
