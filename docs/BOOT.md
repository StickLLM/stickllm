# Booting StickLLM

## Always prefer the USB (recommended)

Plugging the stick in does **not** force USB boot by itself. The PC firmware
boot order does.

On the AMD/ROMED8 host:

1. Enter firmware setup (Del / F2).
2. Put the **StickLLM USB** above the NVMe (Ubuntu).
3. Save & exit.

Until that is set, Ubuntu’s GRUB will keep winning after Ctrl+Alt+Del. You can
still chainload StickLLM from Ubuntu GRUB, but USB-first is the reliable default.

## StickLLM boot menu

| # | Entry | What you get |
|---|---|---|
| **1** | **Server / Local** | On-stick browser when a display is present + LAN UI (`stickllm.chat`). Loopback needs no pair; phone/LAN uses pair code. |
| **2** | **Secure Client** | Menu stub for now (`stickllm.client`) — dedicated client stick in a later release. |
| **3** | **Terminal** | Console login or `ssh user@<ip>` — `nvidia-smi`, `stickllm-status` (`stickllm.ssh`). |

Menu timeout ~**20s**; default is **1 Server / Local**.

### Terminal / SSH credentials (menu 3)

| | |
|---|---|
| User | `user` |
| Password | Random per boot (shown on console) |
| Useful | `stickllm-status` · `nvidia-smi` · `curl -s localhost:8080/health` |

SSH is **off** unless you pick menu **3**.

## NVIDIA / display (do / don’t)

| Do | Don’t |
|---|---|
| Keep boot cmdline `nvidia-drm.modeset=0` so HDMI/console survives | Force `nvidia-drm.modeset=1` on **all** boot entries — blanks HDMI on this profile |
| Let Local enable NVIDIA KMS at **runtime** for cage | Assume QEMU-only flags belong on hardware |
| Real HW kiosk: `WLR_BACKENDS=drm,libinput` | Set `WLR_LIBINPUT_NO_DEVICES=1` on real hardware (QEMU proofs only) |

## Boot sequence (expected)

1. Firmware boots the USB (or Ubuntu GRUB → StickLLM entry).
2. StickLLM menu → pick **1** (Server / Local), **2** (Secure Client stub), or **3** (Terminal).
3. Console: loading (cold boot on a 3090 can take several minutes).
4. **Server / Local / Terminal:** READY with `http://<lan-ip>/` and pair code when the UI path is up.
5. **Local path (checkpoint):** cage + Chromium on the NVIDIA HDMI output; keyboard works.

## First checks

```bash
stickllm-status
nvidia-smi
curl -s localhost:8080/health
curl -s localhost/api/health
```

If chat is slow and `nvidia-smi` shows **0 MiB** used, CUDA never attached.
Check `nvidia_uvm`, `journalctl -u stickllm-llama -b`, and `/run/stickllm/cuda.env`.

Phone on the same LAN: open the Chat UI URL from the READY screen and enter the pair code.

## If it fails

| Symptom | Likely cause |
|---|---|
| Lands in Ubuntu | Firmware boot order — USB not first |
| Firmware ignores USB | Wrong port; try USB2; Secure Boot |
| Black screen, no status | GPU init hang — reboot; try Terminal (menu **3**) to diagnose |
| Local blank / no browser | Wrong ISO (need Local checkpoint); modeset mistake; no DRM |
| Local no keyboard | `WLR_LIBINPUT_NO_DEVICES=1` or missing libinput backend |
| UI up, empty replies | Model missing or still loading |
| Phone cannot connect | Wrong IP / AP client isolation |

## Persist vs ephemeral

- Default: ephemeral (RAM; reboot wipes session).
- **Persist config** is explicit only (`stickllm-persist`).
