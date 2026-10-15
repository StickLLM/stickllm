# Booting StickLLM

Current ship: **v0.3.6** (Drive ISO + [`checksums/v0.3.6.sha256`](../checksums/v0.3.6.sha256)).
Do **not** flash **v0.3.5** (truncated). Flash notes: [FLASH.md](FLASH.md). Vault after
reflash: [VAULT.md](VAULT.md).

## Always prefer the USB (recommended)

Plugging the stick in does **not** force USB boot by itself. The PC firmware
boot order does.

1. Enter firmware setup (Del / F2 — vendor-specific).
2. Put the **StickLLM USB** above internal disks / other OS bootloaders.
3. Save & exit.

Until USB is first, another OS’s bootloader may keep winning after reboot.
Secure Boot: turn **off** (or enroll custom keys later — not required for v0.3.6).

Example lab host (AMD desktop / ROMED8-class board with Ubuntu on NVMe): same
steps — USB above the NVMe entry. That hardware is an example, not a requirement.

## StickLLM boot menu

| # | Entry | What you get |
|---|---|---|
| **1** | **Server / Local** | On-stick browser when a display is present + LAN UI (`stickllm.chat`). Loopback needs no pair; phone/LAN uses pair code. |
| **2** | **Terminal** | Console login or `ssh stickllm@<ip>` — `nvidia-smi`, `stickllm-status` (`stickllm.ssh`). |
| **3** | **Test - SSH Enabled** | Same as Server / Local plus SSH (`stickllm.chat stickllm.ssh`). Random SSH password on READY before the browser takes the screen. |

Menu timeout ~**20s**; default is **1 Server / Local**. Secure Client returns when that path ships.

### Terminal / Test - SSH Enabled credentials (menu 2 / 3)

| | |
|---|---|
| User | `stickllm` |
| Password | Random per boot (shown on console READY; Test - SSH Enabled also prints before kiosk handoff) |
| Useful | `stickllm-status` · `nvidia-smi` · `curl -s localhost:8080/health` |

SSH is **off** unless you pick menu **2** or **3**.

## NVIDIA / display (do / don’t)

| Do | Don’t |
|---|---|
| Keep boot cmdline `nvidia-drm.modeset=0` so HDMI/console survives | Force `nvidia-drm.modeset=1` on **all** boot entries — blanks HDMI on this profile |
| Let Local enable NVIDIA KMS at **runtime** for cage | Assume QEMU-only flags belong on hardware |
| Real HW kiosk: `WLR_BACKENDS=drm,libinput` | Set `WLR_LIBINPUT_NO_DEVICES=1` on real hardware (QEMU proofs only) |

## Boot sequence (expected)

1. Firmware boots the USB (or chainload from another bootloader).
2. StickLLM menu → pick **1** (Server / Local), **2** (Terminal), or **3** (Test - SSH Enabled).
3. Console: UI loading (no model auto-load — Activate from Models when ready).
4. **Server / Local / Terminal / Test - SSH Enabled:** READY with `http://<lan-ip>/` and pair code when the UI path is up. Test - SSH Enabled also shows the SSH password.
5. **Local path:** cage + Chromium on the NVIDIA HDMI output when a display is present; keyboard works. Load a model: Models → radio select → context slider → Activate.

## First checks

```bash
stickllm-status
nvidia-smi
curl -s localhost:8080/health
curl -s localhost/api/health
```

If chat is slow and `nvidia-smi` shows **0 MiB** used, CUDA never attached.
Check `nvidia_uvm`, `journalctl -u stickllm-llama -b`, `/run/stickllm/cuda.env`, and
`llama-server --list-devices` (must show `CUDA0`, not only CPU). Backend order is
**CUDA → Vulkan → CPU**; never claim `STICKLLM_BACKEND=cuda` without list-devices
proof. AMD/Intel use `llama-server-vulkan` + Mesa. CPU is last resort only.

Phone on the same LAN: open the Chat UI URL from the READY screen and enter the pair code.

## If it fails

| Symptom | Likely cause |
|---|---|
| Lands in another OS | Firmware boot order — USB not first |
| Firmware ignores USB | Wrong port; try USB2; Secure Boot on |
| Black screen, no status | GPU init hang — reboot; try Terminal (menu **2**) to diagnose |
| Local blank / no browser | Wrong ISO; modeset mistake; no DRM |
| Local no keyboard | `WLR_LIBINPUT_NO_DEVICES=1` or missing libinput backend |
| UI up, empty replies | Model missing or still loading |
| Phone cannot connect | Wrong IP / AP client isolation |

## Persist vs ephemeral

- Default: ephemeral (RAM; reboot wipes session).
- **Persist config** is explicit only (`stickllm-persist`).
