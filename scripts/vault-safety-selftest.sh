#!/bin/bash
# Fail-closed checks for stickllm-vault (no host disk writes).
# Run: bash scripts/vault-safety-selftest.sh
# Or: docker run --rm -v "$PWD:/w" -w /w debian:bookworm bash scripts/vault-safety-selftest.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
V="$ROOT/overlay/usr/local/bin/stickllm-vault"
[[ -f "$V" ]] || { echo "missing $V"; exit 1; }

fail=0
expect_die() {
  local label="$1"; shift
  if "$@" >/tmp/vault-st.out 2>/tmp/vault-st.err; then
    echo "FAIL $label — expected refusal, command succeeded"
    fail=1
  else
    echo "OK   $label (refused)"
  fi
}

# create-partition must always die
expect_die "create-partition disabled" bash "$V" create-partition /dev/sda1

# Block device paths as setup target (will die on need_root or path check —
# without root, need_root fires first; still proves no silent success)
if [[ "$(id -u)" -eq 0 ]]; then
  expect_die "setup /dev/sda" bash "$V" setup /dev/sda 1 <<EOF
NO
EOF
  expect_die "setup /" bash "$V" setup / 1 <<EOF
NO
EOF
else
  expect_die "setup /dev/nvme0n1p1 as non-root" bash "$V" setup /dev/nvme0n1p1 1
  expect_die "setup /boot as non-root" bash "$V" setup /boot 1
fi

# list-disks should be read-only JSON (may need lsblk)
if bash "$V" list-disks >/tmp/vault-list.json 2>/tmp/vault-list.err; then
  if python3 -c "import json; d=json.load(open('/tmp/vault-list.json')); assert d.get('read_only_probe') is True; assert 'Never formats' in (d.get('safety') or '')" 2>/dev/null; then
    echo "OK   list-disks read_only_probe"
  else
    # stdout may be multi-line; try last line
    if python3 -c "import json; lines=open('/tmp/vault-list.json').read().strip().splitlines(); d=json.loads(lines[-1]); assert d.get('read_only_probe') is True" 2>/dev/null; then
      echo "OK   list-disks read_only_probe"
    else
      echo "WARN list-disks parse (ok if not on Linux): $(head -c 120 /tmp/vault-list.err)"
    fi
  fi
else
  echo "WARN list-disks failed off-Linux (expected on Windows host)"
fi

grep -q 'Never formats' "$V" && echo "OK   safety banner in script" || { echo "FAIL safety banner"; fail=1; }
grep -q 'create-partition is disabled' "$V" && echo "OK   partition disabled" || { echo "FAIL partition"; fail=1; }
grep -Eq 'luksFormat.*\$blob|luksFormat \\' "$V" && echo "OK   luksFormat targets blob var" || echo "WARN review luksFormat target"
if grep -nE 'luks_pass .*luksFormat|cryptsetup .*luksFormat' "$V" | grep -v 'blob'; then
  echo "FAIL vault luksFormat is not limited to the blob file"
  fail=1
else
  echo "OK   vault luksFormat stays on the blob file"
fi

S="$ROOT/overlay/usr/local/bin/stickllm-usb-settings"
C="$ROOT/overlay/usr/local/bin/stickllm-usb-claim"
P="$ROOT/overlay/usr/local/lib/stickllm_usb_settings.py"
[[ -f "$S" && -f "$C" && -f "$P" ]] || { echo "FAIL missing USB settings files"; fail=1; }
grep -q 'STICKLLM-SETTINGS' "$S" && echo "OK   settings script names STICKLLM-SETTINGS" || { echo "FAIL settings label"; fail=1; }
grep -q 'assert-part' "$S" && echo "OK   settings format is gated by assert-part" || { echo "FAIL assert-part gate"; fail=1; }
grep -q '/opt/stickllm/speech' "$S" && echo "OK   speech path excluded from settings" || { echo "FAIL speech exclusion"; fail=1; }
if grep -n 'wipefs' "$S" "$C" "$P" >/dev/null; then
  echo "FAIL wipefs in USB settings path"
  fail=1
else
  echo "OK   no wipefs in USB settings path"
fi
if grep -nE 'luksFormat.*/dev/sd|luksFormat.*/dev/nvme' "$S" >/dev/null; then
  echo "FAIL settings luksFormat uses a hardcoded disk"
  fail=1
else
  echo "OK   settings luksFormat is not hardcoded to a disk"
fi
grep -q '256' "$P" && echo "OK   settings size is 256 MiB" || { echo "FAIL settings size"; fail=1; }
grep -q 'settings-only' "$C" && echo "OK   claim can reserve settings without shrinking DATA" || { echo "FAIL settings-only"; fail=1; }
if grep -nE 'resizepart|ntfsresize|resize2fs' "$C" >/dev/null; then
  echo "FAIL claim script can shrink an existing partition"
  fail=1
else
  echo "OK   claim script does not shrink partitions"
fi

# Ensure we never wipefs a partition in vault script
if grep -n 'wipefs' "$V" >/dev/null; then
  echo "FAIL wipefs present in vault script"
  fail=1
else
  echo "OK   no wipefs in vault script"
fi
if grep -nE 'create-partition|/dev/sd\$' "$V" | grep -v disabled | grep -v refuse | grep -v usage >/dev/null; then
  echo "WARN review remaining device mentions"
else
  echo "OK   no active partition create path"
fi

exit "$fail"
