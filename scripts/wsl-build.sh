#!/usr/bin/env bash
# Convenience entry from Windows: run inside WSL Ubuntu.
# Usage (PowerShell): wsl -d Ubuntu -- bash /mnt/c/Users/peter/OneDrive/Documents/stickllm/scripts/wsl-build.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# Normalize CRLF if checked out from Windows
sed -i 's/\r$//' scripts/*.sh 2>/dev/null || true
chmod +x scripts/*.sh live-build/hooks/normal/*.hook.chroot overlay/usr/local/bin/stickllm-* 2>/dev/null || true
exec ./scripts/build.sh
