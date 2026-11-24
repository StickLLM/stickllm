# StickLLM development workflow

Goal: ship features without rebuilding (or patching) an ISO for every tweak.
Hardware validation stays on real sticks (example: 3090 desktop + ASUS laptop).

**Product ISO (this repo / GitHub `StickLLM/stickllm`):** current ship **v0.8.8**, next bake [NEXT-0.8.9.md](NEXT-0.8.9.md). Work on a local disk clone (e.g. `C:\Users\peter\stickllm-sticklink-wt` or `C:\Users\peter\stickllm`). Never use OneDrive. `main` tracks the shipping line.

## Agent Zero fork (separate)

Agent Zero fork changes still use worktree `C:\Users\peter\stickllm-vault-wt` on branch `stickllm-agentzero` when touching that fork. Details of the running A0 stack on the stick: [ARCHITECTURE-AGENTZERO.md](ARCHITECTURE-AGENTZERO.md). Product ISOs for StickLLM itself go under `out/vX.Y.Z/` (not `build-agentzero\`).

## Rules

1. **Feature commits on a feature branch** — iterate with normal git commits.
   Do **not** cut a new ISO per change.
2. **Test on a running stick over SSH** — copy updated scripts/services into the
   live system, restart units, read journals. Rebuild an ISO only when the change
   needs **kernel / drivers / packages / initramfs** (or a clean bake for release).
3. **One clean ISO when the batch is done** — `./scripts/build.sh` (live-build in
   Docker only). **Never patch an ISO** (`docker-patch-iso*`, squashfs inject,
   etc.). Shipping artifacts are immutable; new work gets a new `out/<version>/`.
4. **Hand to the user for HW test**. **Do not tag or push** until the user
   confirms hardware. Flash for a named release line is OK when the user
   explicitly asks; tag/push still wait for HW confirm.

## SSH iterate (preferred)

Boot menu **2 Terminal** or **3 Test - SSH Enabled**. Boot does **not** stop for
vault unlock (UI-only; default Ephemeral). From the READY screen note the
random SSH password, then:

```bash
# example: push one script and restart
scp overlay/usr/local/bin/stickllm-pick-gpus stickllm@<ip>:/tmp/
ssh stickllm@<ip> 'sudo install -m 755 /tmp/stickllm-pick-gpus /usr/local/bin/ && sudo systemctl restart stickllm-llama'
ssh stickllm@<ip> 'journalctl -u stickllm-llama -b --no-pager | tail -80'
```

Useful: `stickllm-status`, `nvidia-smi`, `curl -s localhost:8080/health`,
`/run/stickllm/cuda.env`, `llama-server --list-devices`.

## When you must rebuild

| Change | Path |
|---|---|
| Overlay scripts, UI, systemd units | SSH copy + restart (then one clean ISO at batch end) |
| Package list, NVIDIA/Mesa, cryptsetup | Clean `./scripts/build.sh` |
| llama.cpp CUDA / Vulkan / CPU binaries | `STICKLLM_FORCE_LLAMA_BUILD=1 ./scripts/build-llama-server.sh` then clean ISO |
| Kernel / initramfs / live-boot | Clean ISO only |

Full cut checklist (tag, Drive, NEXT/ISSUES, rolling window): [RELEASE.md](RELEASE.md).

## Clean release bake

```bash
./scripts/verify-host.sh
./scripts/download-model.sh
./scripts/build-llama-server.sh
STICKLLM_VERSION=0.8.8 ./scripts/build.sh
# → out/v0.8.8/StickLLM-v0.8.8.iso + SHA256SUMS
# ISO integrity check runs in-build (reject truncated images like v0.3.5).
```

For a new ship, bump `STICKLLM_VERSION` (e.g. `0.8.9`) — never overwrite an existing
shipping name. Force llama rebuild only if binaries missing:
`STICKLLM_FORCE_LLAMA_BUILD=1 ./scripts/build.sh`.

**ISO names (v0.3.7+):** exactly `StickLLM-vX.Y.Z.iso` under `out/vX.Y.Z/`.  
Through **v0.3.6**, ships used `stickllm-amd-rtx3090-v….hybrid.iso` — leave those
paths and checksums unchanged. Details: [BUILD.md](BUILD.md).

Preserve **N / N-1** restore slots — see [RESTORE.md](RESTORE.md). Current public **N** is
**v0.8.8** (Drive `StickLLM-v0.8.8.iso`); **N-1** is **v0.8.7**. Never overwrite
published checksums or shipping tags. **Do not flash v0.3.5** (truncated).

## After flash

- **Consumers:** Rufus DD or `dd` — [FLASH.md](FLASH.md).
- **Lab Windows:** Rufus first; Samsung Python flasher is maintainer-only — [MAINTAINER.md](MAINTAINER.md).
- No drive letter after isohybrid is normal — the disk is still there.

User runs HW checks. Only after confirm: tag, push, publish checksum. Feature work
that is not kernel/drivers stays on a feature branch: SSH-test first, then one
clean build + QEMU proof + integrity check.

## VirtualBox test VM (`stickllm-v050-test`)

Local test rig on DESKTOP-65FCPD4 for an ISO without flashing a stick. Files live in
`C:\StickLLM-VM` (never OneDrive): `stickllm-v050-test\` (VM), `stick-v050*.vdi` (the ISO
converted with `VBoxManage convertfromraw`, resized to ~60 GB), `host-ssd*.vdi` (200 GB dynamic),
and `vm_ed25519` (VM-only SSH key, no passphrase). Test-vault passcode/recovery files sit in the same
folder. They are throwaway, but never paste them into chats or commits.

Config: EFI, 8 GB RAM (host had ~18 GB free), 8 vCPU, vmsvga, no GPU (CPU-only llama), xHCI.
The stick VDI is on a **USB** storage controller (USB-MSD, shows as `sdb … usb`), so the first-boot
claim makes STICKLLM-DATA + settings on it like a real stick. The host-SSD VDI is SATA `sda`
(already GPT+ext4 `HOSTSSD` in the vault snapshot). NAT forwards:

| Host | Guest | |
|---|---|---|
| http://127.0.0.1:18080 | 80 | web UI (gateway) |
| https://127.0.0.1:18443 | 443 | web UI TLS (self-signed: `curl.exe -sk`) |
| 127.0.0.1:12222 | 22 | SSH as `stickllm` |

Snapshots (both taken **powered off**):
- `vault-created`: claimed stick + HOSTSSD with a 4 GiB test vault at
  `/mnt/stickllm-host/HOSTSSD-sda1/home/nink` and a LUKS USB settings partition. After boot,
  `stickllm-vault status` shows `locked` and it unlocks with the test passcode.
- `fresh-boot`: untouched stick (`stick-v050-fresh.vdi`) + blank SSD (`host-ssd-blank.vdi`), for testing first-boot claim/setup.

Helper `scripts\vm.ps1`:
```powershell
.\scripts\vm.ps1 restore vault-created 2   # restore snapshot, boot headless, GRUB entry 2 (Terminal/SSH)
.\scripts\vm.ps1 start 3                   # boot current state into GRUB entry 3 (Test - SSH Enabled)
.\scripts\vm.ps1 shot                      # PNG of the screen -> out\vmshots\ (READY screen shows SSH password)
.\scripts\vm.ps1 keys <ssh-password>       # install vm_ed25519.pub for this boot (prints KEY_INSTALLED)
.\scripts\vm.ps1 ssh 'sudo -n stickllm-vault status'
.\scripts\vm.ps1 root C:\StickLLM-VM\check.sh   # DEV ONLY: run a bash file (or 'cmd string') as root, print output
.\scripts\vm.ps1 web                       # HTTP codes for 18080 and 18443
.\scripts\vm.ps1 snap <name>               # ACPI shutdown, then offline snapshot
.\scripts\vm.ps1 stop | kill | status | snaps | key enter|down|up|esc | type <text> | boot <1|2|3>
```

Limits and gotchas:
- VirtualBox 6.1 runs on Hyper-V (NEM), because AMD-V is unavailable while Hyper-V is on. Live/online snapshots
  hang the guest after resume, so only take snapshots powered off (`snap` does this).
- The SSH password is random each boot, and `~/.ssh` is in RAM, so run `shot` then `keys` after every boot.
  GRUB entry 2 shows the password on the READY screen. Entries 1 and 3 sit on "Launching browser" (the kiosk
  doesn't render on vmsvga), but the UI still answers through the forwards.
- `stickllm` sudo is limited to stickllm-* tools, and since v0.5.1 the live `user` (tty2 console) has a
  locked password and no sudo beyond the WiFi helpers, so the old `su ... user` root trick is gone.
  For root in the VM use `vm.ps1 root <file.sh|'cmd'>` (dev only): it copies a throwaway
  `stickllm-vmtest` script + oneshot unit into `/tmp/stickllm-hotfix/` and runs
  `sudo -n stickllm-hotfix stickllm-vmtest.service` (the existing SSH-iterate rule, Terminal mode only).
  Output goes to `/tmp/stickllm-vmtest.out` and is printed; the runner lives only in the VM's RAM and is
  not in the image. Put vault confirmations (`STICKLLM_VAULT_*`) as `export` lines at the top of the file.
- GRUB keys are sent blind (Down x12 then Up); if a boot lands in the wrong mode, use `boot <n>`.
- No model is installed and inference is CPU-only, so it is not useful for speed tests. Dynamic VDIs grow on C:.

### VM notes from 0.5.2

- **No AVX in this VM:** VBox 6.1 on NEM/Hyper-V doesn't pass AVX through, so the production llama-server dies with SIGILL. A VM-only SSE build (`GGML_NATIVE/AVX*/FMA/F16C` off) can run a tiny model at ctx 2048 or less. Never put it in an ISO. Don't change VirtualBox or Hyper-V for this.
- **VM stalls:** under host load (e.g. an ISO build) the guest can freeze for ~8 minutes (VBox.log heartbeat flat). Don't treat a timeout during a build as a test failure; rerun.
- **Password after reboot without typing it:** take `VBoxManage controlvm <vm> screenshotpng` (send `keyboardputscancode 2a aa` first if the console blanked). Decode the READY-screen password by matching PSF console font glyphs (OCR misreads look-alike glyphs). Write it to a temp file, install the key from that file, then delete it. Never paste the password into chats or logs. Loopback `/api/health` also carries the per-boot pair code and SSH password, so don't print it whole. **0.6.8 todo:** stricter OCR-friendly splash/SSH charset in `stickllm-ssh-bootstrap` (see CHANGELOG Later).
- **Scripts for `vm.ps1 root`** must have LF line endings. Vault confirmations go in as `export` lines; `mount-host` needs `STICKLLM_VAULT_CONFIRM=MOUNT-HOST` and a device path such as `/dev/sda1`. Pass a test passcode by file (scp, strip CRLF, read into the env, shred), never as an argument.
- **Deploy vs rebuild:** the SSH hotfix path deploys `/usr/local/bin`, UI, systemd units, and `etc/chromium/policies/managed/stickllm-*.json`. Other `/etc` drop-ins may still need a hand install or rebuild.
- **Real-browser tests:** Playwright on the host in `C:\StickLLM-VM\browser-test`, with `--host-resolver-rules=MAP stickllm.test 127.0.0.1` so the LAN path isn't seen as local (with hostname 127.0.0.1 the UI shows "local"). Reach the kiosk through `ssh -N -L 28080:127.0.0.1:80`. Extra NAT rules (e.g. 5451 for add-ons) are runtime only; remove them afterwards.
- **Realistic stick image:** test with the ISO converted and resized to ~60 GB (`VBoxManage modifymedium --resize 61184`). The raw ISO size has no free space, so there is no settings partition and no agent.
- **Build (product ISO):** Git Bash (not WSL), never on OneDrive. `STICKLLM_VERSION=0.8.8 ./scripts/build.sh` → `out/v0.8.8/StickLLM-v0.8.8.iso`. Keep N/N-1 under `out/` — see [RESTORE.md](RESTORE.md). (Historical Agent Zero fork ISOs lived under `build-agentzero\`; do not confuse those with the public product ship.)
- **Copying files:** the agent box copies files into `C:\Users\peter\...`, then you move them into `C:\StickLLM-VM`.
- **Snapshots for 0.5.2** (powered off): `v052-dev-state`, `v052-reflash-base`, `v052-60g-base` (60 GB stick + test-vault SSD), `v052-fresh-base` (fresh 60 GB stick + blank SSD).
- **Flash:** `out\_flash-agentzero-v052-safe-elev.ps1` (elevated) refuses every disk except the USB Samsung Type-C with serial `AA00000000000489`, then reads the stick back and verifies (`out\verify-boot-v052.out`).

