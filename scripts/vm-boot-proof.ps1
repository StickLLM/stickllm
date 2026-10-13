# VM boot proof — hostfwd curl + QMP screendump. Never flashes USB.
# Serial alone is NEVER enough for ISO-READY / SCREENSHOT_PROOF=PASS.
# Agent must Read PNG(s) then re-run with -ScreenshotProofPass if UI pixels OK.
param(
  [Parameter(Mandatory = $true)][string]$Iso,
  [int]$TimeoutSec = 360,
  [ValidateSet("term", "local", "server", "chat")][string]$BootMode = "term",
  [int]$HostFwdPort = 18080,
  [int]$QmpPort = 4445,
  # Set ONLY after a human/agent Read of the screendump PNG confirms UI pixels.
  [switch]$ScreenshotProofPass
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $Root "scripts\lib\Require-ScreenshotProof.ps1")
. (Join-Path $Root "scripts\lib\qmp-screendump.ps1")
if (-not [IO.Path]::IsPathRooted($Iso)) { $Iso = Join-Path $Root $Iso }
if (-not (Test-Path $Iso)) { throw "Missing ISO: $Iso" }

$Qemu = "C:\Program Files\qemu\qemu-system-x86_64.exe"
if (-not (Test-Path $Qemu)) { throw "QEMU missing: $Qemu (winget install SoftwareFreedomConservancy.QEMU)" }

$Qdir = Join-Path $Root "out\_qemu-bootproof"
New-Item -ItemType Directory -Force -Path $Qdir | Out-Null
$Serial = Join-Path $Qdir "serial.log"
$Stderr = Join-Path $Qdir "qemu-stderr.txt"
$Result = Join-Path $Qdir "BOOT-PROOF.txt"
$ScreenPng = Join-Path $Qdir ("screendump-{0}.png" -f $BootMode)
$ScreenPpm = Join-Path $Qdir ("screendump-{0}.ppm" -f $BootMode)
$ReadyOk = Join-Path $Root "out\ISO-READY.txt"
$ReadyBad = Join-Path $Root "out\ISO-NOT-READY.txt"
$Vmlinuz = Join-Path $Qdir "vmlinuz"
$Initrd = Join-Path $Qdir "initrd.img"

Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 1
Remove-Item $Serial, $Stderr, $Result, $ScreenPng, $ScreenPpm -ErrorAction SilentlyContinue

$hash = (Get-FileHash -Algorithm SHA256 $Iso).Hash.ToUpperInvariant()
$name = [IO.Path]::GetFileName($Iso)
$driveHash = "4914087D502D13327DBBD9196C9A4A7DF46EE079D423FF4B0BC6280E1C7B1A48"
$isLocal = ($BootMode -eq "local" -or $BootMode -eq "chat")

function Write-Fail([string]$why) {
  $when = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
  $shot = if (Test-Path $ScreenPng) { $ScreenPng } else { "missing" }
  @(
    "BOOT_PROOF=FAIL"
    "REASON=$why"
    "SHA256=$hash"
    "ISO=$Iso"
    "SCREENSHOT_PROOF=FAIL"
    "SCREENSHOT_PATH=$shot"
    "FLASH_ANY_USB=FORBIDDEN"
    "WHEN=$when"
  ) | Set-Content $ReadyBad -Encoding ascii
  Set-Content $Result -Value @"
BOOT_PROOF=FAIL
REASON=$why
SCREENSHOT_PATH=$shot
SHA256=$hash
WHEN=$when
"@ -Encoding ascii
  if (Test-Path $ReadyOk) { Remove-Item $ReadyOk -Force }
  Write-Host "BOOT_PROOF=FAIL $why SCREEN=$shot"
}

$needExtract = $true
if ((Test-Path $Vmlinuz) -and (Test-Path $Initrd)) {
  if ((Get-Item $Vmlinuz).LastWriteTime -gt (Get-Item $Iso).LastWriteTime.AddMinutes(-1)) {
    $needExtract = $false
  }
}
if ($needExtract) {
  Write-Host "Extracting live kernel/initrd via docker..."
  docker run --rm -v "${Iso}:/iso:ro" -v "${Qdir}:/out" debian:bookworm `
    bash -lc "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq; apt-get install -y -qq xorriso >/dev/null; xorriso -osirrox on -indev /iso -extract /live/vmlinuz /out/vmlinuz -extract /live/initrd.img /out/initrd.img >/dev/null; ls -lh /out/vmlinuz /out/initrd.img"
  if (-not (Test-Path $Vmlinuz) -or -not (Test-Path $Initrd)) {
    Write-Fail "kernel_extract_failed"
    exit 1
  }
}

$modeFlag = switch ($BootMode) {
  "local"  { "stickllm.local" }
  "chat"   { "stickllm.chat" }
  "server" { "" }
  default  { "stickllm.ssh" }
}
# Chat: keep llama (CPU path) so ui=1 api=1 can pass; only mask NVIDIA bits.
# Local legacy: same. Term/server: mask llama for faster console-only proofs unless chat.
if ($BootMode -eq "chat" -or $BootMode -eq "local") {
  $append = @(
    "boot=live components ignore_uuid username=user hostname=stickllm noeject $modeFlag",
    "live-media=/dev/sr0 live-media-path=/live",
    "console=ttyS0,115200n8 console=tty0 systemd.show_status=false loglevel=4",
    "modprobe.blacklist=nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm",
    "module_blacklist=nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm",
    "systemd.mask=nvidia-persistenced.service systemd.mask=stickllm-nvidia.service"
  ) -join " "
} else {
  $append = @(
    "boot=live components ignore_uuid username=user hostname=stickllm noeject $modeFlag",
    "live-media=/dev/sr0 live-media-path=/live",
    "console=ttyS0,115200n8 console=tty0 systemd.show_status=false loglevel=4",
    "nomodeset modprobe.blacklist=nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm",
    "module_blacklist=nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm",
    "systemd.mask=nvidia-persistenced.service systemd.mask=stickllm-nvidia.service systemd.mask=stickllm-llama.service"
  ) -join " "
}
$append = ($append -replace '\s+', ' ').Trim()

function Start-Qemu([string]$accel, [string]$cpu) {
  $netdev = "user,id=n0,hostfwd=tcp:127.0.0.1:${HostFwdPort}-:80"
  # Always virtio-vga + QMP for screendump (Local needs DRM; Term/Server need on-screen READY).
  $gpu = if ($isLocal) { "-device virtio-vga -display none" } else { "-device virtio-vga -display none" }
  # Chat/Local need headroom for CPU llama (3B Q4 + 4k ctx); Term can stay leaner.
  $mem = if ($isLocal) { 6144 } else { 4096 }
  $argLine = "-m $mem -smp 2 -machine q35 -accel $accel -cpu $cpu $gpu -serial `"file:$Serial`" -qmp tcp:127.0.0.1:${QmpPort},server,nowait -netdev $netdev -device virtio-net-pci,netdev=n0 -cdrom `"$Iso`" -boot d -kernel `"$Vmlinuz`" -initrd `"$Initrd`" -append `"$append`""
  return Start-Process -FilePath $Qemu -ArgumentList $argLine -PassThru -WindowStyle Hidden -RedirectStandardError $Stderr
}

Write-Host "ISO=$Iso"
Write-Host "SHA256=$hash"
Write-Host "HOSTFWD=127.0.0.1:$HostFwdPort -> guest:80"
Write-Host "QMP=127.0.0.1:$QmpPort screendump -> $ScreenPng"
$p = $null
$used = $null
$usedCpu = $null
# Local/Chat: never qemu64 (AVX CPU llama SIGILL). Prefer -cpu host under WHPX;
# fall back to max / EPYC if host is rejected. Override: STICKLLM_QEMU_ACCEL=whpx|tcg.
$accelList = if ($env:STICKLLM_QEMU_ACCEL -eq "tcg") {
  @("tcg")
} elseif ($env:STICKLLM_QEMU_ACCEL -eq "whpx") {
  @("whpx,kernel-irqchip=off", "tcg")
} else {
  @("whpx,kernel-irqchip=off", "tcg")
}
$cpuList = if ($isLocal) {
  @("host", "max", "EPYC")
} else {
  @("host", "max", "EPYC", "qemu64")
}
:bootforeach foreach ($accel in $accelList) {
  foreach ($cpu in $cpuList) {
    # TCG cannot usefully do -cpu host; skip to max/EPYC.
    if ($accel -eq "tcg" -and $cpu -eq "host") { continue }
    Remove-Item $Serial, $Stderr -ErrorAction SilentlyContinue
    $p = Start-Qemu $accel $cpu
    Start-Sleep 4
    if (-not $p.HasExited) {
      $used = $accel
      $usedCpu = $cpu
      Write-Host "QEMU pid=$($p.Id) accel=$accel cpu=$cpu"
      break bootforeach
    }
    Write-Host "QEMU exit early accel=$accel cpu=$cpu"
    if (Test-Path $Stderr) { Get-Content $Stderr | Select-Object -First 8 | Write-Host }
    $p = $null
  }
}
if (-not $p) { Write-Fail "qemu_start_failed"; exit 1 }

$deadline = (Get-Date).AddSeconds($TimeoutSec)
$sawNetwork = $false; $sawModel = $false; $sawHealthUi = $false
$sawLanUrl = $false; $sawPairUsable = $false; $sawPairMint = $false
$sawLocalMode = $false; $sawLocalHandoff = $false; $sawLocalChat = $false
$sawKioskBrowser = $false; $sawKioskUiReady = $false; $sawNoDri = $false
$curlOk = $false; $curlBody = ""; $nmHang = $false; $nmFirstSeen = $null
$screen = @{ Ok = $false; Detail = "not_attempted"; Path = $null }

while ((Get-Date) -lt $deadline) {
  if ($p.HasExited) {
    Write-Fail ("qemu_exited_" + $p.ExitCode)
    if (Test-Path $Serial) { Get-Content $Serial -Tail 40 | Write-Host }
    exit 1
  }
  $text = ""
  if (Test-Path $Serial) { $text = Get-Content $Serial -Raw -ErrorAction SilentlyContinue }
  if ($text -match "STICKLLM Network Loading") { $sawNetwork = $true }
  if ($text -match "STICKLLM Model .+ Loading") { $sawModel = $true }
  if ($text -match "STICKLLM_HEALTH[^\r\n]*ui=1") { $sawHealthUi = $true }
  if ($text -match "STICKLLM_LAN_URL\s+https?://\S+") { $sawLanUrl = $true }
  if ($text -match "LAN IP:\s+\d+\.\d+\.\d+\.\d+") { $sawLanUrl = $true }
  if ($text -match "STICKLLM_PAIR_USABLE\s+\d{4,}|STICKLLM_PAIR_MINTED\s+\d{4,}|PAIR CODE:\s+\d{4,}") { $sawPairUsable = $true }
  if ($text -match "STICKLLM_PAIR_MINTED|PAIR CODE") { $sawPairMint = $true }
  if ($text -match "STICKLLM_LOCAL_MODE|StickLLM LOCAL|local mode|bootstatus: chat|Chat \(this screen") { $sawLocalMode = $true }
  if ($text -match "STICKLLM_LOCAL_HANDOFF") { $sawLocalHandoff = $true }
  if ($text -match "STICKLLM_LOCAL_CHAT_START|StickLLM Local") { $sawLocalChat = $true }
  if ($text -match "STICKLLM_KIOSK_BROWSER") { $sawKioskBrowser = $true }
  if ($text -match "STICKLLM_KIOSK_UI_READY") { $sawKioskUiReady = $true }
  if ($text -match "no /dev/dri/card") { $sawNoDri = $true }
  if ($text -match "NetworkManager") {
    if (-not $nmFirstSeen) { $nmFirstSeen = Get-Date }
    elseif (((Get-Date) - $nmFirstSeen).TotalSeconds -gt 120 -and -not ($sawNetwork -or $sawModel)) {
      $nmHang = $true
      break
    }
  }

  if (-not $curlOk) {
    $rootOk = $false; $healthOk = $false
    try {
      $respRoot = Invoke-WebRequest -Uri "http://127.0.0.1:$HostFwdPort/" -UseBasicParsing -TimeoutSec 2
      if ($respRoot.StatusCode -eq 200) { $rootOk = $true }
    } catch { }
    try {
      $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$HostFwdPort/api/health" -UseBasicParsing -TimeoutSec 2
      if ($resp.StatusCode -eq 200 -and $resp.Content -match '"gateway"\s*:\s*"ok"') {
        $healthOk = $true
        $curlBody = $resp.Content.Substring(0, [Math]::Min(200, $resp.Content.Length))
      }
    } catch { }
    if ($rootOk -and $healthOk) {
      $curlOk = $true
      Write-Host "HOST_CURL_OK / + /api/health"
    }
  }

  if ($text -match "STICKLLM_HEALTH[^\r\n]*ui=1[^\r\n]*api=1") { $script:sawUiApi = $true }
  if ($BootMode -eq "chat") {
    # Chat status proof: pair + LAN + ui=1 + host curl. Prefer api=1, but do not
    # block forever — QEMU CPU llama can be slow; HW uses NVIDIA. Screendump must
    # show pair/IP/model/how-to-connect (agent Read + -ScreenshotProofPass).
    if ($sawModel -and $sawLanUrl -and $curlOk -and $sawPairUsable -and $sawHealthUi) {
      Start-Sleep 12
      $screen = Invoke-QmpScreendump -Port $QmpPort -PngPath $ScreenPng -PpmPath $ScreenPpm
      Write-Host "SCREENDUMP $($screen.Detail)"
      break
    }
  } elseif ($isLocal) {
    if ($sawModel -and $curlOk -and ($sawLocalHandoff -or $sawLocalChat) -and ($sawKioskBrowser -or $sawNoDri -or $sawKioskUiReady)) {
      Start-Sleep 15
      $screen = Invoke-QmpScreendump -Port $QmpPort -PngPath $ScreenPng -PpmPath $ScreenPpm
      Write-Host "SCREENDUMP $($screen.Detail)"
      break
    }
  } else {
    if ($sawNetwork -and $sawModel -and $sawLanUrl -and $curlOk -and ($sawPairUsable -or $sawPairMint)) {
      Start-Sleep 8
      $screen = Invoke-QmpScreendump -Port $QmpPort -PngPath $ScreenPng -PpmPath $ScreenPpm
      Write-Host "SCREENDUMP $($screen.Detail)"
      break
    }
  }
  $len = 0
  if (Test-Path $Serial) { $len = (Get-Item $Serial).Length }
  Write-Host ("wait t={0:n0}s mode={8} serial={1} net={2} model={3} lan={4} curl={6} pair={7} kioskBrowser={11} screen={12}" -f `
    ((Get-Date) - $p.StartTime).TotalSeconds, $len, $sawNetwork, $sawModel, $sawLanUrl, $sawHealthUi, $curlOk, $sawPairUsable, $BootMode, $sawLocalHandoff, $sawLocalChat, $sawKioskBrowser, $screen.Ok)
  Start-Sleep 8
}

if (-not $screen.Ok -and -not $p.HasExited) {
  $screen = Invoke-QmpScreendump -Port $QmpPort -PngPath $ScreenPng -PpmPath $ScreenPpm
  Write-Host "SCREENDUMP_FINAL $($screen.Detail)"
}

Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
$when = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$shotPath = if ($screen.Path) { $screen.Path } elseif (Test-Path $ScreenPng) { $ScreenPng } else { "missing" }

if ($nmHang) {
  Write-Fail "networkmanager_hang_over_120s_without_loading_phase"
  exit 1
}

$failReasons = @()
if (-not $curlOk) { $failReasons += "host_curl_failed" }
if (-not $screen.Ok) { $failReasons += "screendump_failed" }
if ($BootMode -eq "chat") {
  if (-not $sawModel) { $failReasons += "no_model_loading_phase" }
  if (-not $sawLanUrl) { $failReasons += "no_lan_ip_or_url" }
  if (-not $sawPairUsable) { $failReasons += "no_usable_pair_code" }
  if (-not $sawHealthUi) { $failReasons += "no_ui1_health" }
  if (-not $script:sawUiApi) { Write-Host "NOTE: api=1 not seen yet (CPU llama still loading); Chat status screendump still required" }
} elseif ($isLocal) {
  if (-not $sawModel) { $failReasons += "no_model_loading_phase" }
  if (-not ($sawLocalHandoff -or $sawLocalChat)) { $failReasons += "no_local_handoff_or_chat" }
  if ($sawNoDri) { $failReasons += "no_dev_dri_card" }
  if (-not $sawKioskBrowser) { $failReasons += "no_STICKLLM_KIOSK_BROWSER" }
} else {
  if (-not $sawNetwork) { $failReasons += "no_network_loading_phase" }
  if (-not $sawModel) { $failReasons += "no_model_loading_phase" }
  if (-not $sawLanUrl) { $failReasons += "no_lan_ip_or_url" }
  if (-not ($sawPairUsable -or $sawPairMint)) { $failReasons += "no_pair_code" }
}

# Screenshot review gate: scripts never auto-PASS pixel proof.
$shotProof = "PENDING_AGENT_READ"
if ($ScreenshotProofPass) {
  if (-not (Test-Path $shotPath) -or ((Get-Item $shotPath).Length -lt 800)) {
    $failReasons += "screenshot_proof_pass_but_image_missing"
  } else {
    $shotProof = "PASS"
  }
} else {
  $failReasons += "screenshot_not_reviewed_use_-ScreenshotProofPass_after_Read_PNG"
}

if ($failReasons.Count -gt 0) {
  Write-Host "--- serial tail ---"
  if (Test-Path $Serial) { Get-Content $Serial -Tail 80 | Write-Host }
  Write-Host "READ_THIS_PNG=$shotPath"
  Write-Fail ($failReasons -join "+")
  exit 1
}

$how = if ($BootMode -eq "chat") { "CHAT_STATUS+SCREENDUMP+HOST_CURL" } elseif ($isLocal) { "LOCAL_KIOSK+SCREENDUMP+HOST_CURL" } else { "PHASES+LAN+SCREENDUMP+HOST_CURL" }
@(
  "BOOT_PROOF=PASS"
  "MODE=$BootMode"
  "HOW=$how via QEMU($used cpu=$usedCpu)"
  "SCREENSHOT_PROOF=$shotProof"
  "SCREENSHOT_PATH=$shotPath"
  "SHA256=$hash"
  "ISO=$Iso"
  "WHEN=$when"
) | Set-Content $Result -Encoding ascii

$readyLines = @(
  "SMOKE=PASS"
  "STAGE=qemu_screendump_hostfwd_proof"
  "QEMU=PASS"
  "LIVE_BOOT=PASS"
  "BOOT_MODE=$BootMode"
  "BOOT_PROOF=$how"
  "SCREENSHOT_PROOF=$shotProof"
  "SCREENSHOT_PATH=$shotPath"
  "MODEL_LOADING=PASS"
  "UI_REACHABLE=PASS"
  "HOST_CURL_PROOF=PASS"
  "UI_HOST_CURL=PASS"
  "HOSTFWD=http://127.0.0.1:$HostFwdPort/"
  "SHA256=$hash"
  "ISO=$Iso"
  "ISO_NAME=$name"
  "DRIVE_V02_GOLDEN_SHA256=$driveHash"
  "DRIVE_PRESERVED=yes"
  "FLASH_VENDORCO=ALLOWED_IF_HASH_MATCHES"
  "NOTE=SCREENSHOT_PROOF=PASS requires agent Read of PNG. Serial-only forbidden."
  "WHEN=$when"
)
if ($BootMode -eq "chat") {
  $readyLines += @("CHAT_STATUS=PASS", "LAN_URL=PASS", "PAIR_PRESENT=PASS", "NOTE_CHAT=QEMU_console_status;_HW_kiosk_shows_web_banner")
} elseif ($isLocal) {
  $readyLines += @("LOCAL_HANDOFF=PASS", "NETWORK_LOADING=N/A_LOCAL", "LAN_URL=N/A_LOCAL", "PAIR_PRESENT=N/A_LOCAL")
} else {
  $readyLines += @("NETWORK_LOADING=PASS", "LAN_URL=PASS", "PAIR_PRESENT=PASS")
}
$readyLines | Set-Content $ReadyOk -Encoding ascii
Remove-Item $ReadyBad -ErrorAction SilentlyContinue
Write-Host "BOOT_PROOF=PASS MODE=$BootMode SCREENSHOT_PROOF=$shotProof PATH=$shotPath"
exit 0
