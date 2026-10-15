#!/usr/bin/env bash
# Fail if ISO is truncated or kernel/initrd cannot be read.
# Usage: iso-integrity-check.sh <iso-path>
set -euo pipefail

ISO="${1:?iso path}"
test -f "$ISO"

bytes=$(stat -c%s "$ISO" 2>/dev/null || stat -f%z "$ISO")
file_sectors=$((bytes / 2048))

# Parse volume size from xorriso; tolerate SORRY on truncated images.
toc=$(xorriso -indev "$ISO" -toc 2>&1 || true)
if echo "$toc" | grep -qi 'ISO image size .* larger than readable size'; then
  echo "FAIL iso-integrity: volume size exceeds file size (truncated ISO)" >&2
  echo "$toc" | grep -E -i 'ISO image size|readable size|Media summary' >&2 || true
  echo "file_bytes=$bytes file_sectors=$file_sectors" >&2
  exit 1
fi

vol_sectors=""
if echo "$toc" | grep -qE 'ISO image size[[:space:]]+[0-9]+s'; then
  vol_sectors=$(echo "$toc" | sed -n 's/.*ISO image size[[:space:]]*\([0-9][0-9]*\)s.*/\1/p' | head -1)
fi
if [[ -n "$vol_sectors" ]]; then
  # Allow a small slack for padding; anything >1MiB short is fatal.
  if (( file_sectors + 512 < vol_sectors )); then
    echo "FAIL iso-integrity: file shorter than ISO volume (truncated)" >&2
    echo "file_sectors=$file_sectors vol_sectors=$vol_sectors" >&2
    exit 1
  fi
fi

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
if ! xorriso -osirrox on -indev "$ISO" -extract /live/vmlinuz "$tmp" >/dev/null 2>&1; then
  echo "FAIL iso-integrity: cannot extract /live/vmlinuz" >&2
  exit 1
fi
vz=$(stat -c%s "$tmp" 2>/dev/null || stat -f%z "$tmp")
if (( vz < 1000000 )); then
  echo "FAIL iso-integrity: /live/vmlinuz too small ($vz bytes)" >&2
  exit 1
fi

if ! xorriso -osirrox on -indev "$ISO" -extract /live/initrd.img "$tmp" >/dev/null 2>&1; then
  echo "FAIL iso-integrity: cannot extract /live/initrd.img" >&2
  exit 1
fi
ird=$(stat -c%s "$tmp" 2>/dev/null || stat -f%z "$tmp")
if (( ird < 1000000 )); then
  echo "FAIL iso-integrity: /live/initrd.img too small ($ird bytes)" >&2
  exit 1
fi

echo "PASS iso-integrity: $ISO (bytes=$bytes vmlinuz=$vz initrd=$ird)"
