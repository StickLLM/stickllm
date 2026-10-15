#!/usr/bin/env bash
set -euo pipefail

echo "StickLLM build-host check"
ok=1

need() {
  if command -v "$1" >/dev/null 2>&1; then
    echo "  OK  $1"
  else
    echo "  MISS $1"
    ok=0
  fi
}

need bash
need curl
need sha256sum || need shasum

if command -v docker >/dev/null 2>&1; then
  echo "  OK  docker"
  if docker info >/dev/null 2>&1; then
    echo "  OK  docker daemon"
  else
    echo "  WARN docker daemon not running — start Docker Desktop / dockerd"
    ok=0
  fi
else
  echo "  MISS docker (required for reproducible live-build)"
  ok=0
fi

# Disk for models + llama compile + live-build (~40 GB free recommended)
if command -v df >/dev/null; then
  avail="$(df -Pk . | awk 'NR==2{print $4}')"
  echo "  info free KiB in cwd fs: $avail (want ≥ 40000000 ≈ 40 GB)"
fi

if [[ "$ok" -ne 1 ]]; then
  echo "Host not ready."
  exit 1
fi
echo "Host OK — run ./scripts/download-model.sh && ./scripts/build-llama-server.sh && ./scripts/build.sh"
