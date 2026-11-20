#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Prefer Local checkpoint ISO; override with ISO=... for Drive golden or other builds.
DEFAULT_ISO="$ROOT/out/v0.2.1-local-nvidia-kbd/stickllm-amd-rtx3090-v0.2-local-nvidia-kbd.hybrid.iso"
GOLDEN_ISO="$ROOT/out/stickllm-amd-rtx3090.hybrid.iso"
if [[ -z "${ISO:-}" ]]; then
  if [[ -f "$DEFAULT_ISO" ]]; then ISO="$DEFAULT_ISO"
  else ISO="$GOLDEN_ISO"
  fi
fi
DEV="${1:-}"

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

if [[ -z "$DEV" ]]; then
  echo "Usage: ISO=path/to.iso $0 /dev/sdX"
  lsblk -d -o NAME,SIZE,MODEL,TRAN,RM
  exit 1
fi
if [[ ! -f "$ISO" ]]; then echo "Missing ISO: $ISO — run ./scripts/build.sh first"; exit 1; fi
if [[ ! -b "$DEV" ]]; then echo "Not a block device: $DEV"; exit 1; fi
RM="$(lsblk -dn -o RM "$DEV")"
if [[ "$RM" != "1" ]]; then echo "Refusing: $DEV is not removable"; exit 1; fi
echo "ISO: $ISO"
lsblk -o NAME,SIZE,MODEL,LABEL "$DEV"
read -r -p "Type FLASH to wipe and write $DEV: " C
[[ "$C" == "FLASH" ]] || { echo "Aborted"; exit 1; }
sudo wipefs -a "$DEV"
sudo dd if="$ISO" of="$DEV" bs=4M status=progress oflag=sync
sync
echo "Done. Eject $DEV and boot with Secure Boot disabled."
