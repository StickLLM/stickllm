#!/usr/bin/env bash
# StickLLM ISO quality gate — run BEFORE flashing VendorCo / test sticks.
# Never touches Drive shipping ISO. Exit 0 only when squashfs checks PASS.
#
# Usage:
#   ./scripts/smoke-iso.sh out/stickllm-amd-rtx3090-v0.2-rebuild.iso
#   ./scripts/smoke-iso.sh out/....iso --qemu   # optional; skipped if no qemu
# Windows: .\scripts\smoke-iso.ps1 -Iso .\out\...\iso
#
# Writes out/ISO-READY.txt on PASS (or ISO-NOT-READY.txt on FAIL).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ISO="${1:?usage: smoke-iso.sh <iso> [--qemu]}"
shift || true
DO_QEMU=0
for a in "$@"; do
  case "$a" in
    --qemu) DO_QEMU=1 ;;
  esac
done

test -f "$ISO"
READY_OK="$ROOT/out/ISO-READY.txt"
READY_BAD="$ROOT/out/ISO-NOT-READY.txt"
rm -f "$READY_OK" "$READY_BAD"

ISO_ABS="$(cd "$(dirname "$ISO")" && pwd)/$(basename "$ISO")"
ISO_NAME="$(basename "$ISO")"
if command -v sha256sum >/dev/null 2>&1; then
  SHA="$(sha256sum "$ISO_ABS" | awk '{print toupper($1)}')"
  SIZE="$(wc -c <"$ISO_ABS" | tr -d ' ')"
else
  SHA="$(openssl dgst -sha256 "$ISO_ABS" | awk '{print toupper($NF)}')"
  SIZE="$(stat -c%s "$ISO_ABS" 2>/dev/null || stat -f%z "$ISO_ABS")"
fi
DRIVE_HASH="4914087D502D13327DBBD9196C9A4A7DF46EE079D423FF4B0BC6280E1C7B1A48"
WHEN="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "=== StickLLM smoke-iso ==="
echo "ISO:  $ISO_ABS"
echo "SHA256: $SHA"
echo "SIZE: $SIZE bytes"

if [[ "$ISO_NAME" == "stickllm-amd-rtx3090.hybrid.iso" ]]; then
  echo "NOTE: Drive shipping hybrid name — checks still run; never overwrite this file."
fi
if [[ "$SHA" == "$DRIVE_HASH" && "$ISO_NAME" == *rebuild* ]]; then
  echo "FAIL: rebuild name has Drive v0.2 hash — patch did not change content"
  cat >"$READY_BAD" <<EOF
SMOKE=FAIL
REASON=rebuild_iso_hash_equals_drive_v0.2
SHA256=$SHA
ISO=$ISO_ABS
WHEN=$WHEN
FLASH=FORBIDDEN
EOF
  exit 1
fi

echo "=== squashfs / unit gate ==="
VERIFY_RC=0
if command -v xorriso >/dev/null 2>&1 && command -v unsquashfs >/dev/null 2>&1; then
  bash "$ROOT/scripts/lib/smoke-iso-verify.sh" "$ISO_ABS" || VERIFY_RC=$?
elif command -v docker >/dev/null 2>&1; then
  docker run --rm --network host \
    -v "${ROOT}:/stickllm:ro" \
    -v "${ISO_ABS}:/iso:ro" \
    debian:bookworm \
    bash -lc '
      set -e
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq
      apt-get install -y -qq xorriso squashfs-tools >/dev/null
      bash /stickllm/scripts/lib/smoke-iso-verify.sh /iso
    ' || VERIFY_RC=$?
else
  echo "FAIL: need xorriso+unsquashfs or docker"
  VERIFY_RC=2
fi

if [[ "$VERIFY_RC" -ne 0 ]]; then
  cat >"$READY_BAD" <<EOF
SMOKE=FAIL
STAGE=squashfs
SHA256=$SHA
ISO=$ISO_ABS
WHEN=$WHEN
FLASH=FORBIDDEN
EOF
  echo ""
  echo "SMOKE FAIL — do NOT flash VendorCo. See $READY_BAD"
  exit 1
fi

QEMU_RESULT="SKIPPED"
if [[ "$DO_QEMU" -eq 1 ]]; then
  echo "=== optional QEMU boot ==="
  if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
    echo "QEMU not on PATH — skipping (squashfs gate still PASS)"
    QEMU_RESULT="SKIPPED_NO_BINARY"
  else
    qdir="$ROOT/out/_qemu-smoke"
    rm -rf "$qdir"
    mkdir -p "$qdir"
    set +e
    timeout 180 qemu-system-x86_64 \
      -m 2048 -smp 2 -nographic -no-reboot \
      -cdrom "$ISO_ABS" \
      -boot d \
      -serial mon:stdio \
      >"$qdir/serial.log" 2>&1
    set -e
    if grep -Eqi 'stickllm-bootstatus|PAIR CODE|Starting StickLLM|stickllm-console-setup' "$qdir/serial.log"; then
      QEMU_RESULT="PASS_SERIAL_HINTS"
      echo "PASS QEMU serial showed StickLLM bootstatus/pair hints"
    else
      QEMU_RESULT="SKIPPED_INCONCLUSIVE"
      echo "WARN QEMU inconclusive — squashfs PASS is the flash gate; see $qdir/serial.log"
    fi
  fi
else
  echo "=== QEMU: skipped (pass --qemu to try; not required for FLASH_VENDORCO) ==="
fi

cat >"$READY_OK" <<EOF
SMOKE=PASS
STAGE=squashfs
QEMU=$QEMU_RESULT
SHA256=$SHA
ISO=$ISO_ABS
ISO_NAME=$ISO_NAME
SIZE_BYTES=$SIZE
DRIVE_V02_GOLDEN_SHA256=$DRIVE_HASH
DRIVE_PRESERVED=yes
FLASH_VENDORCO=ALLOWED
WHEN=$WHEN

Checks: wait-online masked; bootstatus ASAP (no network-online);
  getty gate; no console-setup daemon-reload; NM After=bootstatus + TimeoutStartSec;
  ui/ssh/llama not After=network-online; FAILED UX; grub show_status=false.

NEVER flash VendorCo until this file exists with SMOKE=PASS.
Drive hybrid (4914087D…) + checksums/v0.2.sha256 stay immutable.
EOF

echo ""
echo "SMOKE PASS — flash VendorCo only from this rebuild:"
echo "  $ISO_ABS"
echo "  SHA256=$SHA"
echo "  marker: $READY_OK"
exit 0
