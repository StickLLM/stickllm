# Windows-friendly ISO quality gate (Docker; no WSL required).
# NEVER flash VendorCo until out/ISO-READY.txt says SMOKE=PASS.
#
#   .\scripts\smoke-iso.ps1 -Iso .\out\stickllm-amd-rtx3090-v0.2-rebuild.iso
#   .\scripts\smoke-iso.ps1 -Iso .\out\...\iso -Qemu
param(
  [Parameter(Mandatory = $true)]
  [string]$Iso,
  [switch]$Qemu
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not [IO.Path]::IsPathRooted($Iso)) { $Iso = Join-Path $Root $Iso }
if (-not (Test-Path $Iso)) { throw "Missing ISO: $Iso" }

$readyOk = Join-Path $Root "out\ISO-READY.txt"
$readyBad = Join-Path $Root "out\ISO-NOT-READY.txt"
Remove-Item $readyOk, $readyBad -ErrorAction SilentlyContinue

$hash = (Get-FileHash -Algorithm SHA256 $Iso).Hash.ToUpperInvariant()
$size = (Get-Item $Iso).Length
$name = [IO.Path]::GetFileName($Iso)
$driveHash = "4914087D502D13327DBBD9196C9A4A7DF46EE079D423FF4B0BC6280E1C7B1A48"
$when = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

Write-Host "=== StickLLM smoke-iso.ps1 ==="
Write-Host "ISO: $Iso"
Write-Host "SHA256: $hash"
Write-Host "SIZE: $size"

if ($name -match "rebuild" -and $hash -eq $driveHash) {
  @(
    "SMOKE=FAIL"
    "REASON=rebuild_iso_hash_equals_drive_v0.2"
    "SHA256=$hash"
    "ISO=$Iso"
    "WHEN=$when"
    "FLASH=FORBIDDEN"
  ) | Set-Content -Path $readyBad -Encoding ascii
  throw "FAIL: rebuild ISO hash equals Drive v0.2 - patch did not change content"
}

Write-Host "=== squashfs / unit gate (docker) ==="
$dockerScript = @'
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq xorriso squashfs-tools >/dev/null
bash /stickllm/scripts/lib/smoke-iso-verify.sh /iso
'@

docker run --rm --network host `
  -v "${Root}:/stickllm:ro" `
  -v "${Iso}:/iso:ro" `
  debian:bookworm `
  bash -lc $dockerScript

if ($LASTEXITCODE -ne 0) {
  @(
    "SMOKE=FAIL"
    "STAGE=squashfs"
    "SHA256=$hash"
    "ISO=$Iso"
    "WHEN=$when"
    "FLASH=FORBIDDEN"
  ) | Set-Content -Path $readyBad -Encoding ascii
  Write-Host "SMOKE FAIL - do NOT flash. See $readyBad"
  exit $LASTEXITCODE
}

$qemuResult = "SKIPPED"
if ($Qemu) {
  if (Get-Command qemu-system-x86_64 -ErrorAction SilentlyContinue) {
    Write-Host "QEMU present but Windows serial smoke is best-effort; marking SKIPPED_WINDOWS"
    $qemuResult = "SKIPPED_WINDOWS"
  } else {
    Write-Host "QEMU not on PATH - squashfs PASS is the flash gate"
    $qemuResult = "SKIPPED_NO_BINARY"
  }
} else {
  Write-Host "=== QEMU: skipped (not required for FLASH_VENDORCO) ==="
}

@(
  "SMOKE=PASS"
  "STAGE=squashfs"
  "QEMU=$qemuResult"
  "SHA256=$hash"
  "ISO=$Iso"
  "ISO_NAME=$name"
  "SIZE_BYTES=$size"
  "DRIVE_V02_GOLDEN_SHA256=$driveHash"
  "DRIVE_PRESERVED=yes"
"FLASH_VENDORCO=FORBIDDEN"
"LIVE_BOOT=UNPROVEN"
"WHEN=$when"
""
"Squashfs gate PASS only. FLASH is FORBIDDEN until LIVE_BOOT=PASS"
"(QEMU or real Term proving bootstatus/pair-code). See out/_qemu-bootproof/."
"Drive hybrid (4914087D...) + checksums/v0.2.sha256 stay immutable."
) | Set-Content -Path $readyOk -Encoding ascii

Write-Host ""
Write-Host "SQUASHFS PASS - NOT enough to flash. Need LIVE_BOOT=PASS next."
Write-Host "  $Iso"
Write-Host "  SHA256=$hash"
Write-Host "  marker: $readyOk (FLASH_VENDORCO=FORBIDDEN until live proof)"
exit 0
