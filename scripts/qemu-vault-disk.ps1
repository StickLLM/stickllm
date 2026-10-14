# Create a disposable QEMU virtual disk FILE with one ext4 filesystem for vault tests.
# Never touches host partition tables. Never writes under out/v0.3.2/.
param(
  [int]$SizeGb = 8,
  [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $OutDir) { $OutDir = Join-Path $Root "out\_qemu-vault" }

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

$inner = @'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq e2fsprogs util-linux >/dev/null
# Build on container local disk first (OneDrive/Windows bind mounts often reject sparse truncate).
IMG=/tmp/vault-testdisk.img
rm -f "$IMG"
truncate -s __SIZE__G "$IMG"
LOOP=$(losetup -f --show "$IMG")
mkfs.ext4 -F -L STICKVAULTTEST "$LOOP"
losetup -d "$LOOP"
ls -lh "$IMG"
rm -f /out/vault-testdisk.img /out/vault-testdisk.img.tmp
cp "$IMG" /out/vault-testdisk.img.tmp
mv -f /out/vault-testdisk.img.tmp /out/vault-testdisk.img
ls -lh /out/vault-testdisk.img
'@
$inner = $inner.Replace('__SIZE__', "$SizeGb")
$innerPath = Join-Path $OutDir "_mkdisk.sh"
[System.IO.File]::WriteAllText($innerPath, ($inner -replace "`r`n", "`n"))

docker run --rm --privileged `
  -v "${OutDir}:/out" `
  debian:bookworm `
  bash /out/_mkdisk.sh
if ($LASTEXITCODE -ne 0) { throw "mkdisk docker failed exit=$LASTEXITCODE" }
if (-not (Test-Path $Img)) { throw "mkdisk did not produce $Img" }

@"
StickLLM QEMU vault test disk (disposable FILE)
==============================================
Image: $Img
Size:  ${SizeGb} GiB sparse, single ext4, label STICKVAULTTEST
Host partitions: NEVER touched.

QEMU attach example (second disk; -cpu host when available):
  -drive file=$Img,if=virtio,format=raw,cache=writeback

Proof (no full ISO): scripts/vault-qemu-proof.ps1
"@ | Set-Content $Readme -Encoding utf8

Write-Host "OK $Img"
