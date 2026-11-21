#!/usr/bin/env bash
# Download Method C manylinux wheels into the overlay wheelhouse (build host only).
# The ISO bake installs from this directory with --no-index (no network on stick).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REQ="$ROOT/overlay/usr/local/lib/stickllm-methodc-requirements.txt"
DEST="$ROOT/overlay/opt/stickllm/methodc-wheelhouse"
mkdir -p "$DEST"

export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

echo "=== Vendoring Method C wheels → ${DEST} ==="
# Debian 13 (trixie) ships Python 3.13 — Method C venv must use cp313 wheels.
# Host Docker bridge can be flaky on this lab; prefer --network host.
docker run --rm --network host \
  -v "${REQ}:/req.txt:ro" \
  -v "${DEST}:/wheels" \
  python:3.13-bookworm \
  bash -lc '
    set -euo pipefail
    pip install -q pip==25.0.1
    pip download \
      -r /req.txt \
      -d /wheels \
      --python-version 313 \
      --only-binary=:all: \
      --platform manylinux_2_17_x86_64 \
      --platform manylinux2014_x86_64 \
      --implementation cp \
      --abi cp313
    # Also pull any pure-python fallbacks required by the set.
    pip download -r /req.txt -d /wheels --no-binary=:none: --python-version 313 2>/dev/null || true
    ls -lh /wheels | tail -n +1
    echo "WHEEL_COUNT=$(ls -1 /wheels | wc -l)"
  '

# Refuse empty wheelhouse
count="$(find "$DEST" -type f \( -name "*.whl" -o -name "*.tar.gz" \) | wc -l | tr -d " ")"
if [[ "${count}" -lt 5 ]]; then
  echo "REFUSE: wheelhouse too small (${count} artifacts)" >&2
  exit 1
fi
echo "Vendored ${count} artifacts into overlay/opt/stickllm/methodc-wheelhouse"
echo "$DEST" > "$DEST/VENDOR_STAMP.txt"
date -u +"%Y-%m-%dT%H:%M:%SZ" >> "$DEST/VENDOR_STAMP.txt"
