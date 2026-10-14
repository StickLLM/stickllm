# Create a disposable QEMU virtual disk FILE with one ext4 filesystem for vault SSH tests.
# Never touches host partition tables. Never writes under out/v0.3.2/.
# Output: out/_qemu-vault/vault-testdisk.img (+ README). Attach as second virtio disk later.
param(
  [int]$SizeGb = 8,
  [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $OutDir) { $OutDir = Join-Path $Root "out\_qemu-vault" }

# Hard refuse shipping ISO dirs
$forbidden = @(
  (Join-Path $Root "out\v0.3.2"),
  (Join-Path $Root "out\v0.3.1"),
  (Join-Path $Root "out\v0.3.0"),
  (Join-Path $Root "out\v0.2.0")
)
foreach ($f in $forbidden) {
  if ($OutDir -like "$f*") { throw "Refusing to write under shipping out/ dir: $OutDir" }
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$Img = Join-Path $OutDir "vault-testdisk.img"
$Readme = Join-Path $OutDir "README.txt"

if ($SizeGb -lt 2 -or $SizeGb -gt 64) { throw "SizeGb must be 2-64 for the disposable test disk" }

Write-Host "Creating sparse test disk (Docker loop+ext4) → $Img"
# Build image inside Debian container: truncate sparse file, losetup, mkfs.ext4, detach.
# No partition table rewrite on the Windows host.
docker run --rm --privileged `
  -v "${OutDir}:/out" `
  debian:bookworm `
  bash -lc @"
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq e2fsprogs util-linux >/dev/null
IMG=/out/vault-testdisk.img
rm -f \"\$IMG\"
truncate -s ${SizeGb}G \"\$IMG\"
LOOP=\$(losetup -f --show \"\$IMG\")
mkfs.ext4 -F -L STICKVAULTTEST \"\$LOOP\"
losetup -d \"\$LOOP\"
ls -lh \"\$IMG\"
"@

@"
StickLLM QEMU vault test disk (disposable FILE)
==============================================
Image: $Img
Size:  ${SizeGb} GiB sparse, single ext4, label STICKVAULTTEST
Host partitions: NEVER touched.

QEMU attach example (second disk; -cpu host when available):
  -drive file=$Img,if=virtio,format=raw,cache=writeback

Inside guest (after boot Term/Test):
  sudo mkdir -p /mnt/vault-test
  sudo mount -t ext4 /dev/vdb /mnt/vault-test   # or /dev/vda if only this disk
  # If the whole disk is ext4 with no partition table, mount the disk node directly.
  sudo stickllm-vault setup /mnt/vault-test/StickLLM 2
  sudo stickllm-vault status
  sudo stickllm-vault lock
  sudo stickllm-vault unlock
  sudo stickllm-vault grow 1

Safety: setup only creates models/ + stickllm-vault.img under the chosen folder.
Never formats the host OS drive. Wipe this image anytime: delete $Img
"@ | Set-Content $Readme -Encoding utf8

Write-Host "OK $Img"
Write-Host "See $Readme"
