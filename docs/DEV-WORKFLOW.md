# StickLLM development workflow

Goal: ship features without rebuilding (or patching) an ISO for every tweak.
Hardware validation stays on real sticks (example: 3090 desktop + ASUS laptop).

The working branch for Agent Zero is `stickllm-agentzero`. Do not fast-forward `main` until that line is accepted. Work on `C:\Users\peter\stickllm-vault-wt`. Never use OneDrive.

## Agent Zero fork

1. Change the fork and test it on the stick with `sudo -n stickllm-hotfix`.
2. Rebuild one clean ISO into `build-agentzero\` (not `out\`, not OneDrive).
3. Nink tests that ISO on hardware.
4. Push the fork after that test. Do not flash unless Nink asks.

Keep the current Agent Zero ISO and the previous two (`n-2`) under `build-agentzero\`. Do not delete those restore copies to make room. Name the build `stickllm-agentzero-v0.5.1.iso` (About shows `0.5.1 · Agent Zero v0.5` from `stickllm.json`). Build it with `STICKLLM_VERSION=0.5.1 STICKLLM_ISO_PATH=build-agentzero/stickllm-agentzero-v0.5.1.iso ./scripts/build.sh`. The v0.5.0 and v0.4 ISOs stay as restore copies; the running stick is not replaced until Nink has tested 0.5.1. Details of the running system: [ARCHITECTURE-AGENTZERO.md](ARCHITECTURE-AGENTZERO.md).

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

## Clean release bake

```bash
./scripts/verify-host.sh
./scripts/download-model.sh
./scripts/build-llama-server.sh
./scripts/build.sh
# → out/v0.3.7/StickLLM-v0.3.7.iso + SHA256SUMS
# ISO integrity check runs in-build (reject truncated images like v0.3.5).
```

Optional: `STICKLLM_VERSION=0.4.0 ./scripts/build.sh`. Force llama rebuild only if
binaries missing: `STICKLLM_FORCE_LLAMA_BUILD=1 ./scripts/build.sh`.

**ISO names (v0.3.7+):** exactly `StickLLM-vX.Y.Z.iso` under `out/vX.Y.Z/`.  
Through **v0.3.6**, ships used `stickllm-amd-rtx3090-v….hybrid.iso` — leave those
paths and checksums unchanged. Details: [BUILD.md](BUILD.md).

Preserve N-2 restore slots — see [RESTORE.md](RESTORE.md). Current public **N** is
**v0.3.6** (Drive). **N-1** `v0.3.0` ISO is local/maintainer only. Never overwrite
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
