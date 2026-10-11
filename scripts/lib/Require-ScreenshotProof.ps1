# Shared flash/boot gate: SCREENSHOT_PROOF=PASS + PNG paths must exist.
# Dot-source from flash scripts. Never treat serial-only as enough.
function Assert-ScreenshotProof {
  param(
    [string]$ReadyPath = "",
    [switch]$AllowMissingReady
  )
  $root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
  if (-not $ReadyPath) { $ReadyPath = Join-Path $root "out\ISO-READY.txt" }
  $notReady = Join-Path $root "out\ISO-NOT-READY.txt"

  if (Test-Path $notReady) {
    throw "REFUSE: ISO-NOT-READY.txt present - screenshot/hostfwd proof incomplete"
  }
  if (-not (Test-Path $ReadyPath)) {
    if ($AllowMissingReady) { return }
    throw "REFUSE: missing ISO-READY.txt"
  }
  $rt = Get-Content $ReadyPath -Raw -ErrorAction Stop
  if ($rt -notmatch '(?m)^SCREENSHOT_PROOF=PASS\s*$') {
    throw "REFUSE: SCREENSHOT_PROOF=PASS missing (serial-only / unread screendump forbidden)"
  }
  $paths = @()
  foreach ($line in ($rt -split "`r?`n")) {
    if ($line -match '^SCREENSHOT_PATH=(.+)$') { $paths += $Matches[1].Trim() }
    if ($line -match '^SCREENSHOT_PATHS=(.+)$') {
      foreach ($p in ($Matches[1] -split ';')) {
        $t = $p.Trim()
        if ($t) { $paths += $t }
      }
    }
  }
  if ($paths.Count -eq 0) {
    throw "REFUSE: SCREENSHOT_PROOF=PASS but no SCREENSHOT_PATH/SCREENSHOT_PATHS in ISO-READY"
  }
  foreach ($p in $paths) {
    if (-not (Test-Path $p)) { throw "REFUSE: screendump missing: $p" }
    if ((Get-Item $p).Length -lt 800) { throw "REFUSE: screendump too small (empty/corrupt): $p" }
  }
  Write-Host "SCREENSHOT_PROOF_GATE_OK paths=$($paths -join '; ')"
}
