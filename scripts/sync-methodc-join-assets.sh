#!/usr/bin/env bash
# Copy frozen Method C join browser assets into the signalling Worker public/
# tree for Cloudflare static hosting. Does not modify lab-browser-e2e sources.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/sticklink-server/lab-browser-e2e"
DST="$ROOT/sticklink-server/worker/public"
rm -rf "$DST"
mkdir -p "$DST/browser" "$DST/node_modules/@noble"
cp -a "$SRC/browser/." "$DST/browser/"
for pkg in curves ciphers hashes; do
  cp -a "$SRC/node_modules/@noble/$pkg" "$DST/node_modules/@noble/$pkg"
done
cat >"$DST/JOIN_ASSETS_STAMP.txt" <<EOF
source=sticklink-server/lab-browser-e2e/browser (+ @noble)
build=methodc-lte-accept-20261108.1
host=link.stickllm.com static join only — no A0 proxy
copied=$(date -Iseconds 2>/dev/null || date)
EOF
echo "Synced join assets → $DST"
