#!/usr/bin/env bash
# Reproducible StickLLM live ISO build (Debian live-build in Docker).
# Profile: amd-rtx3090 only.
#
# Important on Windows: live-build/debootstrap must run on a Docker named
# volume (Linux fs). Building directly on a OneDrive/NTFS bind mount fails
# with "Tried to extract package, but file already exists".
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROFILE="amd-rtx3090"
# v0.3.1 ships under out/v0.3.1/ — never overwrite Drive golden v0.2
# or published out/v0.3.0 / checksums/v0.3.sha256.
VERSION_DIR="v0.3.1"
ISO_NAME="stickllm-${PROFILE}-v0.3.1.hybrid.iso"
CHECKSUM_FILE="checksums/v0.3.1.sha256"
MODEL_3B="qwen2.5-3b-instruct-q4_k_m.gguf"
MODEL_SHARD1="qwen2.5-7b-instruct-q5_k_m-00001-of-00002.gguf"
MODEL_SHARD2="qwen2.5-7b-instruct-q5_k_m-00002-of-00002.gguf"
VOL_WORK="stickllm-lb-work"

echo "=== StickLLM build (${PROFILE}) ==="
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
    # Never treat the Drive golden v0.2 name as the new build artifact.
    [[ "$(basename "$f")" == "stickllm-amd-rtx3090.hybrid.iso" ]] && continue
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
# Also leave a copy at out/${ISO_NAME} for scripts that look there (not the golden name).
cp -f "$SRC_ISO" "out/${ISO_NAME}"
(
  cd "out/${VERSION_DIR}"
  sha256sum "${ISO_NAME}" > "SHA256SUMS"
)
cp -f "out/${VERSION_DIR}/SHA256SUMS" "$CHECKSUM_FILE"

ls -lh "out/${VERSION_DIR}/${ISO_NAME}"
echo "=== Build complete: out/${VERSION_DIR}/${ISO_NAME} ==="
echo "Checksum: ${CHECKSUM_FILE}"
echo "Flash with docs/FLASH.md (Windows: .\\scripts\\flash-windows.ps1 -DriveLetter E)"
echo "Note: does not overwrite checksums/v0.3.sha256 (v0.3.0 N ship) or Drive golden."
