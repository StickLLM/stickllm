#!/usr/bin/env bash
# Fail if ISO is truncated or kernel/initrd cannot be read.
# Usage: iso-integrity-check.sh <iso-path>
#
# Needs xorriso. On Windows/Git Bash (no host xorriso), falls back to Docker
# when `docker` is available — same cold-start dependency as the ISO build.
set -euo pipefail

ISO="${1:?iso path}"
test -f "$ISO"

# Resolve absolute path for Docker bind mounts (Git Bash / MSYS may rewrite).
iso_abs() {
  local p="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath "$p"
  elif command -v readlink >/dev/null 2>&1; then
    readlink -f "$p" 2>/dev/null || (
      cd "$(dirname "$p")" && echo "$(pwd -P)/$(basename "$p")"
    )
  else
    cd "$(dirname "$p")" && echo "$(pwd -P)/$(basename "$p")"
  fi
}

run_check() {
  local ISO="$1"
  local bytes file_sectors toc vol_sectors tmp vz ird

  bytes=$(stat -c%s "$ISO" 2>/dev/null || stat -f%z "$ISO")
  file_sectors=$((bytes / 2048))

  # Parse volume size from xorriso; tolerate SORRY on truncated images.
  toc=$(xorriso -indev "$ISO" -toc 2>&1 || true)
  if echo "$toc" | grep -qi 'ISO image size .* larger than readable size'; then
    echo "FAIL iso-integrity: volume size exceeds file size (truncated ISO)" >&2
    echo "$toc" | grep -E -i 'ISO image size|readable size|Media summary' >&2 || true
    echo "file_bytes=$bytes file_sectors=$file_sectors" >&2
    return 1
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
      return 1
    fi
  fi

  tmp=$(mktemp)
  # shellcheck disable=SC2064
  trap 'rm -f "$tmp"' RETURN
  if ! xorriso -osirrox on -indev "$ISO" -extract /live/vmlinuz "$tmp" >/dev/null 2>&1; then
    echo "FAIL iso-integrity: cannot extract /live/vmlinuz" >&2
    return 1
  fi
  vz=$(stat -c%s "$tmp" 2>/dev/null || stat -f%z "$tmp")
  if (( vz < 1000000 )); then
    echo "FAIL iso-integrity: /live/vmlinuz too small ($vz bytes)" >&2
    return 1
  fi

  if ! xorriso -osirrox on -indev "$ISO" -extract /live/initrd.img "$tmp" >/dev/null 2>&1; then
    echo "FAIL iso-integrity: cannot extract /live/initrd.img" >&2
    return 1
  fi
  ird=$(stat -c%s "$tmp" 2>/dev/null || stat -f%z "$tmp")
  if (( ird < 1000000 )); then
    echo "FAIL iso-integrity: /live/initrd.img too small ($ird bytes)" >&2
    return 1
  fi

  echo "PASS iso-integrity: $ISO (bytes=$bytes vmlinuz=$vz initrd=$ird)"
}

if command -v xorriso >/dev/null 2>&1; then
  run_check "$ISO"
  exit $?
fi

# Avoid docker-in-docker recursion when already inside the fallback container.
if [[ "${STICKLLM_ISO_INTEGRITY_INNER:-}" == "1" ]]; then
  echo "FAIL iso-integrity: xorriso missing inside integrity container" >&2
  exit 1
fi

if command -v docker >/dev/null 2>&1; then
  ABS="$(iso_abs "$ISO")"
  DIR="$(dirname "$ABS")"
  BASE="$(basename "$ABS")"
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  echo "iso-integrity: host has no xorriso — using Docker (debian:bookworm)" >&2
  # Disable MSYS path rewriting for Docker -v args on Git Bash / Windows.
  export MSYS_NO_PATHCONV=1
  export MSYS2_ARG_CONV_EXCL='*'
  docker run --rm \
    -e STICKLLM_ISO_INTEGRITY_INNER=1 \
    -v "${SCRIPT_DIR}/iso-integrity-check.sh:/check.sh:ro" \
    -v "${DIR}:/iso:ro" \
    debian:bookworm \
    bash -c 'set -euo pipefail
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq
      apt-get install -y -qq xorriso >/dev/null
      bash /check.sh "/iso/'"${BASE}"'"'
  exit $?
fi

echo "FAIL iso-integrity: need xorriso on PATH, or docker (for fallback)" >&2
exit 1
