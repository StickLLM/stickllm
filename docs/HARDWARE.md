# Known-good hardware matrix

## v0.2 / Local checkpoint (current)

| Field | Required |
|---|---|
| Profile ID | `amd-rtx3090` |
| CPU | AMD desktop x86_64 |
| RAM | 32 GB minimum (62 GB class OK) |
| GPU | NVIDIA GeForce RTX 3090 (24 GB VRAM) |
| Display (Local) | Monitor on the **NVIDIA** HDMI/DP path (checkpoint `v0.2.1-local-nvidia-kbd`) |
| Input (Local) | USB keyboard via DRM + libinput (cage + Chromium) |
| Firmware | USB-first boot recommended; Secure Boot off for NVIDIA modules |
| Storage (host) | Not used by default |
| USB stick | **16 GB** OK for base; **32–64 GB** recommended for `STICKLLM-DATA` downloads |
| Network | Optional LAN for phone clients; needed for model upgrades |

Baked models today: small text GGUFs on the ISO (3B + 7B class). Larger models (e.g. 27B) download to DATA when catalog-pinned and space allows.

## Target model tiers (by VRAM)

See [MODELS.md](MODELS.md). Planned defaults:

| VRAM | Qwen series | Role |
|---|---|---|
| RAM-only / failsafe | lite | Survival / slow CPU |
| 8 GB | ~8B | Small GPU |
| 12 GB | ~14B | Mid |
| 16 GB | compact quant | Large |
| **24 GB** | **27B-class Q4** | **Default multipurpose (download)** |

## Why 3090 first

- Mature CUDA path (`sm_86`)
- 24 GB fits 27B Q4 with headroom
- Dual-3090 machines need careful `CUDA_VISIBLE_DEVICES` (single large GPU by default)

## Explicitly unsupported (for now)

- Intel / Apple Silicon hosts as first-class profiles  
- AMD GPUs (ROCm profile later)  
- Secure Boot with signed NVIDIA modules  
- Automatic use of internal disks (SSD cache is future **opt-in** only)  
- Local kiosk on a non-NVIDIA display path (no auto DRM pick yet)
