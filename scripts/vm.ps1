# StickLLM VirtualBox test VM helper (DESKTOP-65FCPD4). VM files live in C:\StickLLM-VM (not OneDrive).
# Usage: .\scripts\vm.ps1 <start [grub#]|stop|kill|status|shot|web|restore [snap] [grub#]|snap <name>|snaps|keys <ssh-password>|ssh [cmd]|type <text>|key <enter|down|up|esc>|boot <1|2|3>>
# Ports: 127.0.0.1:18080->80 (UI http), 127.0.0.1:18443->443 (UI https), 127.0.0.1:12222->22 (SSH). See docs/DEV-WORKFLOW.md.
param([Parameter(Position=0)][string]$Cmd='status',[Parameter(Position=1,ValueFromRemainingArguments=$true)][string[]]$Rest)
$ErrorActionPreference='Continue'
$vb='C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
$vm='stickllm-v050-test'
$key='C:\StickLLM-VM\vm_ed25519'
$shots=Join-Path (Split-Path $PSScriptRoot) 'out\vmshots'   # out/ is git-ignored
function State { ((& $vb showvminfo $vm --machinereadable) | Select-String '^VMState=').ToString().Split('=')[1].Trim('"') }
$sc=@{ enter='1c 9c'; down='e0 50 e0 d0'; up='e0 48 e0 c8'; esc='01 81'; '1'='02 82'; '2'='03 83'; '3'='04 84' }
function Key($k){ & $vb controlvm $vm keyboardputscancode ($sc[$k] -split ' ') }
# GRUB has a 20 s timeout and no wrap: spam Down to reach entry 3, then walk Up to the wanted entry.
function Pick($n){ for($i=0;$i -lt 22;$i++){ Key 'down'; Start-Sleep -Milliseconds 700 }; for($i=3;$i -gt $n;$i--){ Key 'up'; Start-Sleep -Milliseconds 300 }; Key 'enter' }
switch ($Cmd) {
  'start'   { # optional arg: GRUB entry (default 2 = Terminal/SSH). 0 = leave GRUB default (1 Server/Local)
              $n= if ($Rest) { [int]$Rest[0] } else { 2 }; & $vb startvm $vm --type headless; if ($n -gt 0) { Start-Sleep 3; Pick $n } }
  'stop'    { & $vb controlvm $vm acpipowerbutton }
  'kill'    { & $vb controlvm $vm poweroff }
  'status'  { State; & $vb showvminfo $vm --machinereadable | Select-String '^(Forwarding|CurrentSnapshotName)' }
  'shot'    { New-Item -ItemType Directory -Force $shots | Out-Null; $f=Join-Path $shots ('shot-{0:yyyyMMdd-HHmmss}.png' -f (Get-Date)); & $vb controlvm $vm screenshotpng $f; $f }
  'snap'    { # powered-off snapshot (acpi shutdown first)
              if ((State) -eq 'running') { & $vb controlvm $vm acpipowerbutton; for($i=0;$i -lt 24 -and (State) -ne 'poweroff';$i++){ Start-Sleep 5 }; if ((State) -ne 'poweroff') { & $vb controlvm $vm poweroff; Start-Sleep 3 } }; & $vb snapshot $vm take $Rest[0] }
  'snaps'   { & $vb snapshot $vm list }
  'restore' { # restore [snapshot=vault-created] [grub entry=2]; snapshots are powered-off (NEM cannot resume live state)
              $s= if ($Rest) { $Rest[0] } else { 'vault-created' }; $n= if ($Rest.Count -gt 1) { [int]$Rest[1] } else { 2 }
              if ((State) -eq 'running') { & $vb controlvm $vm poweroff; Start-Sleep 3 }; & $vb snapshot $vm restore $s; & $vb startvm $vm --type headless; Start-Sleep 3; Pick $n }
  'type'    { & $vb controlvm $vm keyboardputstring ($Rest -join ' ') }
  'keys'    { # install C:\StickLLM-VM\vm_ed25519.pub for user stickllm. Arg = this boot's SSH password (READY screen). Not logged.
              $pl=(Get-Command plink -ErrorAction Stop).Source; $pw=Join-Path $env:TEMP ('vmpw-{0}.tmp' -f $PID); Set-Content -Path $pw -Value $Rest[0] -NoNewline
              try {
                $fp=((& $pl -ssh -batch -P 12222 stickllm@127.0.0.1 exit 2>&1) | Select-String 'SHA256:\S+').Matches[0].Value
                $pub=(Get-Content "$key.pub").Trim()
                & $pl -ssh -batch -hostkey $fp -P 12222 -pwfile $pw stickllm@127.0.0.1 "mkdir -p ~/.ssh && grep -qxF '$pub' ~/.ssh/authorized_keys 2>/dev/null || echo '$pub' >> ~/.ssh/authorized_keys; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys; echo KEY_INSTALLED"
              } finally { Remove-Item $pw -ErrorAction SilentlyContinue } }
  'key'     { Key $Rest[0] }
  'boot'    { # reset running VM into GRUB entry: 1=Server/Local 2=Terminal 3=Test-SSH
              & $vb controlvm $vm reset; Start-Sleep 2; Pick ([int]$Rest[0]) }
  'ssh'     { ssh -i $key -p 12222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o LogLevel=ERROR -o BatchMode=yes -o ConnectTimeout=10 stickllm@127.0.0.1 @Rest }
  'web'     { foreach($u in 'http://127.0.0.1:18080/','https://127.0.0.1:18443/'){ curl.exe -sk -m 15 -o NUL -w ('{0} %{{http_code}}\n' -f $u) $u } }
  default   { Get-Content $PSCommandPath -TotalCount 3 }
}
