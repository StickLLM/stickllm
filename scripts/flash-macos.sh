#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEFAULT_ISO="$ROOT/out/v0.2.1-local-nvidia-kbd/stickllm-amd-rtx3090-v0.2-local-nvidia-kbd.hybrid.iso"
GOLDEN_ISO="$ROOT/out/stickllm-amd-rtx3090.hybrid.iso"
if [[ -z "${ISO:-}" ]]; then
  if [[ -f "$DEFAULT_ISO" ]]; then ISO="$DEFAULT_ISO"
  else ISO="$GOLDEN_ISO"
  fi
fi
DISK="${1:-}"

READY="${ROOT}/out/ISO-READY.txt"
NOTREADY="${ROOT}/out/ISO-NOT-READY.txt"
if [[ -f "$NOTREADY" ]]; then echo "REFUSE: ISO-NOT-READY present"; exit 1; fi
if [[ ! -f "$READY" ]]; then echo "REFUSE: missing ISO-READY.txt"; exit 1; fi
grep -q '^SCREENSHOT_PROOF=PASS$' "$READY" || { echo "REFUSE: SCREENSHOT_PROOF=PASS missing"; exit 1; }
while IFS= read -r line; do
  case "$line" in
    SCREENSHOT_PATH=*) p="${line#SCREENSHOT_PATH=}"; [[ -f "$p" ]] || { echo "REFUSE: missing $p"; exit 1; } ;;
    SCREENSHOT_PATHS=*)
      IFS=';' read -ra ps <<< "${line#SCREENSHOT_PATHS=}"
      for p in "${ps[@]}"; do
        p=$(echo "$p" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        [[ -z "$p" || "$p" == "missing" ]] && continue
        [[ -f "$p" ]] || { echo "REFUSE: missing $p"; exit 1; }
      done
      ;;
  esac
done < "$READY"
echo "SCREENSHOT_PROOF_GATE_OK"

if [[ -z "$DISK" ]]; then
  echo "Usage: ISO=path/to.iso $0 /dev/diskN"
  diskutil list
  exit 1
fi
if [[ ! -f "$ISO" ]]; then echo "Missing ISO: $ISO"; exit 1; fi
echo "ISO: $ISO"
diskutil info "$DISK" | egrep 'Device Identifier|Disk Size|Removable|Protocol' || true
read -r -p "Type FLASH to wipe and write $DISK: " C
[[ "$C" == "FLASH" ]] || { echo "Aborted"; exit 1; }
diskutil unmountDisk "$DISK"
RAW="${DISK/disk/rdisk}"
sudo dd if="$ISO" of="$RAW" bs=4m status=progress
sync
diskutil eject "$DISK"
echo "Done. Boot with Secure Boot disabled."
