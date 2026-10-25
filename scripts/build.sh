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
# Next unshipped line. Override: STICKLLM_VERSION=0.4.2 ./scripts/build.sh
# Never point this at a published ship (v0.2.0 / v0.3.0 / v0.3.6 / v0.3.8 / v0.3.9 / v0.4.0 / v0.4.1).
VERSION="${STICKLLM_VERSION:-0.4.2}"
VERSION_DIR="v${VERSION}"
ISO_NAME="${STICKLLM_ISO_NAME:-StickLLM-v${VERSION}.iso}"
OUT_DIR="${STICKLLM_OUT_DIR:-out}"
CHECKSUM_FILE="checksums/v${VERSION}.sha256"
MODEL_3B="qwen2.5-3b-instruct-q4_k_m.gguf"
VOL_WORK="stickllm-lb-work"

case "$VERSION_DIR" in
  v0.2.0|v0.2.1-local-nvidia-kbd|v0.3.0|v0.3.1|v0.3.2|v0.3.3|v0.3.4|v0.3.5|v0.3.6|v0.3.7|v0.3.8|v0.3.9|v0.4.0|v0.4.1)
    echo "REFUSE: VERSION=${VERSION} would overwrite a shipping artifact" >&2
    exit 1
    ;;
esac

echo "=== StickLLM build (${ISO_NAME}) ==="
./scripts/verify-host.sh

if [[ ! -f "models/${MODEL_3B}" ]]; then
  echo "3B GGUF missing — fetching the baked base model…"
  ./scripts/download-model.sh
fi

echo "Speech assets (image build only; the stick does not download these)…"
if [[ -x /c/Python314/python.exe ]]; then
  /c/Python314/python.exe scripts/download-speech.py
elif command -v python3 >/dev/null 2>&1; then
  python3 scripts/download-speech.py
else
  python scripts/download-speech.py
fi

./scripts/build-llama-server.sh

mkdir -p "$OUT_DIR"

# Git Bash on Windows rewrites Unix-style Docker paths; disable conversion.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

docker volume create "$VOL_WORK" >/dev/null

echo "Assembling live-build tree on Docker volume ${VOL_WORK}…"

docker run --rm --privileged --network host \
  -e "STICKLLM_DEBIAN_MIRROR=${STICKLLM_DEBIAN_MIRROR:-}" \
  -e "STICKLLM_DEBIAN_SECURITY_MIRROR=${STICKLLM_DEBIAN_SECURITY_MIRROR:-}" \
  -v "${ROOT}:/stickllm:ro" \
  -v "${ROOT}/${OUT_DIR}:/stickllm-out" \
  -v "${VOL_WORK}:/work" \
  -w //work \
  debian:bookworm \
  bash //stickllm/scripts/lib/docker-build-live.sh

mkdir -p "${OUT_DIR}/${VERSION_DIR}"
# Prefer hybrid iso freshly written by docker-build-live into the out dir.
SRC_ISO=""
# docker-build-live writes live-image-amd64.hybrid.iso. A previous
# ISO of the same name must not shadow that fresh hybrid.
if [[ -f "${OUT_DIR}/live-image-amd64.hybrid.iso" ]]; then
  SRC_ISO="${OUT_DIR}/live-image-amd64.hybrid.iso"
elif [[ -f "${OUT_DIR}/${ISO_NAME}" ]]; then
  SRC_ISO="${OUT_DIR}/${ISO_NAME}"
elif compgen -G "${OUT_DIR}/*.hybrid.iso" >/dev/null; then
  shopt -s nullglob
  for f in "${OUT_DIR}"/*.hybrid.iso; do
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
  echo "ERROR: no new ISO in ${OUT_DIR}/"
  ls -la "$OUT_DIR" || true
  exit 1
fi
if [[ -n "${STICKLLM_ISO_PATH:-}" ]]; then
  mkdir -p "$(dirname "$STICKLLM_ISO_PATH")"
  cp -f "$SRC_ISO" "$STICKLLM_ISO_PATH"
  if [[ "$SRC_ISO" != "$STICKLLM_ISO_PATH" ]]; then
    rm -f "$SRC_ISO"
  fi
  (
    cd "$(dirname "$STICKLLM_ISO_PATH")"
    sha256sum -b "$(basename "$STICKLLM_ISO_PATH")" > "$(basename "$STICKLLM_ISO_PATH").sha256"
  )
  ls -lh "$STICKLLM_ISO_PATH"
  echo "=== Build complete: ${STICKLLM_ISO_PATH} ==="
  echo "Checksum: ${STICKLLM_ISO_PATH}.sha256"
else
  cp -f "$SRC_ISO" "${OUT_DIR}/${VERSION_DIR}/${ISO_NAME}"
  # Also leave a copy at ${OUT_DIR}/${ISO_NAME} for scripts that look there (not a shipping name).
  if [[ "$SRC_ISO" != "${OUT_DIR}/${ISO_NAME}" ]]; then
    cp -f "$SRC_ISO" "${OUT_DIR}/${ISO_NAME}"
  fi
  (
    cd "${OUT_DIR}/${VERSION_DIR}"
    sha256sum -b "${ISO_NAME}" > "SHA256SUMS"
  )
  if [[ "$OUT_DIR" == "out" ]]; then
    cp -f "${OUT_DIR}/${VERSION_DIR}/SHA256SUMS" "$CHECKSUM_FILE"
  fi
  ls -lh "${OUT_DIR}/${VERSION_DIR}/${ISO_NAME}"
  echo "=== Build complete: ${OUT_DIR}/${VERSION_DIR}/${ISO_NAME} ==="
  echo "Checksum: ${CHECKSUM_FILE}"
fi
echo "Flash: docs/FLASH.md (Rufus DD on Windows, or dd on Linux)"
echo "Note: does not overwrite checksums/v0.3.6.sha256 or Drive golden; Naming: StickLLM-vX.Y.Z.iso"
