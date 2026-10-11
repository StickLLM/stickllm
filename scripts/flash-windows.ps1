#Requires -RunAsAdministrator
param(
  [string]$Iso = "",
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^[A-Za-z]$')]
  [string]$DriveLetter
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $Root "scripts\lib\Require-ScreenshotProof.ps1")
Assert-ScreenshotProof

if (-not $Iso) {
  $checkpoint = Join-Path $Root "out\v0.2.1-local-nvidia-kbd\stickllm-amd-rtx3090-v0.2-local-nvidia-kbd.hybrid.iso"
  $golden = Join-Path $Root "out\stickllm-amd-rtx3090.hybrid.iso"
  if (Test-Path $checkpoint) { $Iso = $checkpoint }
  else { $Iso = $golden }
}

if (-not (Test-Path $Iso)) {
  Write-Error "Missing ISO: $Iso — build with WSL: ./scripts/build.sh"
}

$letter = $DriveLetter.ToUpper()
$vol = Get-Volume -DriveLetter $letter -ErrorAction SilentlyContinue
if (-not $vol) { Write-Error "No volume for ${letter}:" }
if ($vol.DriveType -ne 'Removable') {
  Write-Error "Refusing: ${letter}: is DriveType=$($vol.DriveType) (need Removable)"
}

Write-Host "ISO:  $Iso"
Write-Host "USB:  ${letter}:  label=$($vol.FileSystemLabel)  size=$([math]::Round($vol.Size/1GB,2)) GB"
Write-Host ""
Write-Host "This ERASES the USB and writes a raw hybrid ISO (DD mode)."
$confirm = Read-Host "Type FLASH to continue"
if ($confirm -ne "FLASH") { Write-Host "Aborted."; exit 1 }

$wslIso = (wsl wslpath -a "$Iso").Trim()
$part = Get-Partition -DriveLetter $letter
$diskNumber = $part.DiskNumber
$phys = "\\\\.\\PhysicalDrive$diskNumber"

Write-Host "PhysicalDrive$diskNumber → $phys"
Write-Host ""
Write-Host "Recommended on Windows: use Rufus in DD Image mode."
Write-Host "  ISO: $Iso"
Write-Host "  Target: ${letter}: (PhysicalDrive$diskNumber)"
Write-Host ""
Write-Host "Attempting WSL raw write (requires USB visible as /dev/sdX in WSL)…"

$sd = wsl bash -lc "lsblk -dn -o NAME,SIZE,RM,MODEL | awk '\$3==1{print \$1, \$2, \$4}'"
Write-Host "WSL removable disks:`n$sd"
$dev = Read-Host "Enter WSL device name only (e.g. sdc) or press Enter to abort and use Rufus"
if (-not $dev) { Write-Host "Aborted — use Rufus DD mode."; exit 1 }

wsl bash -lc "set -e; test -b /dev/$dev; wipefs -a /dev/$dev; dd if='$wslIso' of=/dev/$dev bs=4M status=progress oflag=sync"
Write-Host "Done. Eject ${letter}: and boot with Secure Boot disabled."
