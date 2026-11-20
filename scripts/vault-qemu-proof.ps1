# Non-destructive vault proof on a virtual disk FILE (never host partitions).
# Creates out/_qemu-vault/vault-testdisk.img, then setup/lock/unlock/grow in Docker.
# Same file is QEMU-attachable (-drive … -cpu host). No out/v0.3.2, no ISO/tag/push.
param(
  [int]$SizeGb = 4,
  [switch]$SkipCreateDisk
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$OutDir = Join-Path $Root "out\_qemu-vault"
$Img = Join-Path $OutDir "vault-testdisk.img"
$Result = Join-Path $OutDir "VAULT-PROOF.txt"
$VaultSrc = Join-Path $Root "overlay\usr\local\bin\stickllm-vault"

foreach ($f in @("v0.3.2", "v0.3.1", "v0.3.0", "v0.2.0")) {
  if ($OutDir -like "*\out\$f*") { throw "Refusing shipping out/$f" }
}
if (-not (Test-Path $VaultSrc)) { throw "Missing $VaultSrc" }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
if (-not $SkipCreateDisk -or -not (Test-Path $Img)) {
  Write-Host "Creating virtual disk via qemu-vault-disk.ps1…"
  & (Join-Path $Root "scripts\qemu-vault-disk.ps1") -SizeGb $SizeGb -OutDir $OutDir
}

$proofScript = @'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq cryptsetup cryptsetup-bin e2fsprogs util-linux openssl python3 >/dev/null

# Copy virt disk into container local storage (reliable losetup on Docker Desktop).
test -f /data/vault-testdisk.img
cp -f /data/vault-testdisk.img /tmp/vault-testdisk.img
IMG=/tmp/vault-testdisk.img
cp /data/stickllm-vault /usr/local/bin/stickllm-vault
chmod 755 /usr/local/bin/stickllm-vault
sed -i 's/\r$//' /usr/local/bin/stickllm-vault

mkdir -p /mnt/vault-test /run/stickllm /var/lib/stickllm
# Clear leftover mapper/mount from a prior privileged Docker run on this VM.
umount /var/lib/stickllm/vault 2>/dev/null || true
cryptsetup close stickllm-vault 2>/dev/null || true
# Prefer direct mount of the image file; fall back to losetup.
if ! mount -t ext4 -o loop "$IMG" /mnt/vault-test 2>/tmp/mnt.err; then
  LOOP=$(losetup -f --show "$IMG")
  mount -t ext4 "$LOOP" /mnt/vault-test
  echo "$LOOP" >/tmp/vault-proof.loop
fi
# Fresh folder each proof (avoid leftover blob from partial prior run on same image).
rm -rf /mnt/vault-test/StickLLM
mkdir -p /mnt/vault-test/StickLLM

export STICKLLM_RUN=/run/stickllm
export STICKLLM_VAULT_META=/run/stickllm/vault-meta
export STICKLLM_VAULT_MNT=/var/lib/stickllm/vault
export STICKLLM_VAULT_CONFIRM=CREATE-VAULT
export STICKLLM_VAULT_CONFIRM_SAVED=SAVED
export STICKLLM_VAULT_CONFIRM_SPACE=SPACE-OK
export STICKLLM_VAULT_PASS='testpass-qemu-proof'
export STICKLLM_VAULT_PASS2='testpass-qemu-proof'
export STICKLLM_VAULT_WIPE_AFTER=0

echo "=== refuse block device ==="
if stickllm-vault setup /dev/sda 1 >/tmp/refuse.out 2>/tmp/refuse.err; then
  echo "FAIL: setup /dev/sda should refuse"; exit 1
fi
echo "OK refuse device path"

echo "=== setup ==="
stickllm-vault setup /mnt/vault-test/StickLLM 1 | tee /tmp/setup.out
grep -q 'RECOVERY_PHRASE:' /tmp/setup.out
test -f /mnt/vault-test/StickLLM/stickllm-vault.img
test -d /mnt/vault-test/StickLLM/models
findmnt -n /var/lib/stickllm/vault >/dev/null
echo "OK setup"

echo "=== lock ==="
stickllm-vault lock
if findmnt -n /var/lib/stickllm/vault >/dev/null 2>&1; then
  echo "FAIL still mounted"; exit 1
fi
echo "OK lock"

echo "=== unlock ==="
export STICKLLM_VAULT_PASS='testpass-qemu-proof'
stickllm-vault unlock
findmnt -n /var/lib/stickllm/vault >/dev/null
echo "OK unlock"

echo "=== grow ==="
export STICKLLM_VAULT_CONFIRM=GROW-VAULT
export STICKLLM_VAULT_PASS='testpass-qemu-proof'
stickllm-vault grow 1
echo "OK grow"

echo "=== list-disks read-only ==="
stickllm-vault list-disks | tail -1 | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("read_only_probe") is True'
echo "OK list-disks"

stickllm-vault lock || true
umount /var/lib/stickllm/vault 2>/dev/null || true
cryptsetup close stickllm-vault 2>/dev/null || true
umount /mnt/vault-test || true
if [[ -f /tmp/vault-proof.loop ]]; then
  losetup -d "$(cat /tmp/vault-proof.loop)" 2>/dev/null || true
fi

echo "VAULT_PROOF=PASS"
'@

$proofPath = Join-Path $OutDir "_proof-inner.sh"
[System.IO.File]::WriteAllText($proofPath, ($proofScript -replace "`r`n", "`n"))
Copy-Item $VaultSrc (Join-Path $OutDir "stickllm-vault") -Force

Write-Host "Running vault proof in Docker against virt disk (no host disks)..."
docker run --rm --privileged `
  -v "${OutDir}:/data" `
  debian:bookworm `
  bash /data/_proof-inner.sh
$code = $LASTEXITCODE
if ($code -ne 0) {
  Set-Content -Path $Result -Encoding ascii -Value @(
    'VAULT_PROOF=FAIL'
    "DISK=$Img"
    "DOCKER_EXIT=$code"
  )
  throw "vault proof failed docker_exit=$code result=$Result"
}

$when = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
Set-Content -Path $Result -Encoding ascii -Value @(
  'VAULT_PROOF=PASS'
  "DISK=$Img"
  'METHOD=docker-loop-ext4-file (QEMU-attachable; no host partitions)'
  'CHECKS=refuse-dev,setup,lock,unlock,grow,list-disks-readonly'
  "WHEN=$when"
)

Write-Host "VAULT_PROOF=PASS result=$Result"
Get-Content $Result
