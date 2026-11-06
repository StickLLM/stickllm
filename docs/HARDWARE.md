# Hardware

## Minimum (advertised)

| Field | Minimum |
|---|---|
| System RAM | **16 GB** |
| GPU | **8 GB** VRAM |

Do **not** advertise **4 GB** GPU (or lower) as supported. **Qwen3.5-4B** remains
an optional catalog download for weak cards / RAM-only; it is not a product tier
and is not the Open default. Default baked model is **Qwen2.5-7B Instruct Q4_K_M**
for the **8 GB** minimum. See [MAINTAINER.md](MAINTAINER.md) and [MODELS.md](MODELS.md).

## GPU backends

| Vendor | Backends |
|---|---|
| **AMD** | ROCm and Vulkan |
| **NVIDIA** | CUDA |
| **Intel GPU** | Vulkan |

Inference falls back across available backends (then CPU) when a preferred path is missing
or fails. Minimum remains **16 GB** system RAM · **8 GB** GPU.

## Tested hardware

User-confirmed boots only (not an exhaustive compatibility matrix):

| Vendor | Confirmed |
|---|---|
| **NVIDIA** | Single RTX 3090; dual RTX 3090s |
| **AMD** | Single RX 570; single RX 580 |

## Known-good lab matrix (v0.2 / Local checkpoint)

Development and HW confirm gear — not the retail minimum above.

| Field | Lab known-good |
|---|---|
| Profile ID | `amd-rtx3090` |
| CPU | AMD desktop x86_64 |
| RAM | 32 GB (62 GB class OK) |
| GPU | NVIDIA GeForce RTX 3090 (24 GB VRAM) |
| Display (Local) | Monitor on the **NVIDIA** HDMI/DP path (checkpoint `v0.2.1-local-nvidia-kbd`) |
| Input (Local) | USB keyboard via DRM + libinput (cage + Chromium) |
| Firmware | USB-first boot recommended; Secure Boot off for NVIDIA modules |
| Storage (host) | Not used by default |
| USB stick | **16 GB** OK for base; **32–64 GB** recommended for `STICKLLM-DATA` downloads |
| Network | Optional LAN for phone clients; needed for model upgrades |

Baked models today (through v0.3.8): small text GGUFs on the ISO (3B + 7B class).
Next ship (ISS-020): bake 3B only; 7B+ download to DATA when catalog-pinned and space allows.

## Target model tiers (by VRAM)

See [MODELS.md](MODELS.md) for the full recommend table. Advertised hosts start at **8 GB**:

| VRAM | Recommend | Role |
|---|---|---|
| Below 8 GB (not advertised) | Qwen3.5-4B (optional download) | Weak-host fallback only |
| **8 GB** (minimum) | **Qwen2.5-7B Q4_K_M** (baked) | Installed default |
| 12 GB | Qwen2.5-14B Q4_K_M | Optional download |
| 16 GB | Qwen2.5-32B Q3_K_M | Optional download |
| **24 GB** | **Qwen3.8-27B Q4_K_M** | Optional download |
| 32 GB | Qwen2.5-32B Q4_K_M | Optional download |
| Dual 24 GB | Qwen2.5-72B Q3_K_M | Optional download (CUDA tensor-split) |

## Why 3090 first

- Mature CUDA path (`sm_86`)
- 24 GB fits 27B Q4 with headroom
- Dual-3090 machines use CUDA **tensor-split** for the dual-24 GB recommend (72B Q3); Vulkan remains one-card

## Explicitly unsupported (for now)

- Apple Silicon hosts as first-class profiles  
- Secure Boot with signed NVIDIA modules  
- Automatic use of internal disks (SSD cache is future **opt-in** only)  
- Local kiosk on a non-NVIDIA display path (no auto DRM pick yet)
