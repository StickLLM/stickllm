# Building the ISO

## ISO filename convention

| Era | Pattern | Example |
|-----|---------|---------|
| **v0.3.7+** (new ships) | `StickLLM-vX.Y.Z.iso` | `StickLLM-v0.3.7.iso` |
| Through **v0.3.6** (historical) | `stickllm-amd-rtx3090-v….hybrid.iso` | `stickllm-amd-rtx3090-v0.3.6.hybrid.iso` |

Default for current amd64 ships: **exactly** `StickLLM-vX.Y.Z.iso` (example: `StickLLM-v0.3.7.iso`) — no `.hybrid`, no GPU/profile/arch segment. Add an arch/variant suffix only when shipping a distinct platform later (e.g. `StickLLM-vX.Y.Z-arm64.iso`). Do **not** rename or rewrite already-shipped artifacts (v0.3.6 and earlier stay under their old names/checksums).

Override the next build version: `STICKLLM_VERSION=0.4.0 ./scripts/build.sh` → `StickLLM-v0.4.0.iso`.

## Host requirements

- Docker Desktop (Linux containers) with ≥ 20 GB free disk
- Bash (Git Bash on Windows, or Linux/macOS)
- Network (first build pulls Debian packages, CUDA devel image, GGUF ~5.4 GB)

WSL2 Ubuntu is optional. On this workstation the preferred path is **Git Bash + Docker Desktop**.

## One-shot

```bash
./scripts/verify-host.sh
./scripts/download-model.sh      # ~5.4 GB Q5_K_M (2 shards)
./scripts/build-llama-server.sh  # CUDA + Vulkan + CPU llama-server in nvidia/cuda container
./scripts/build.sh               # Debian live-build → out/v0.3.7/StickLLM-v0.3.7.iso
```

Or: `./scripts/build.sh` (calls the above as needed). Dev loop (SSH first, no ISO patch): [DEV-WORKFLOW.md](DEV-WORKFLOW.md).

## What the ISO contains

- Debian Bookworm live (UEFI hybrid)
- Proprietary NVIDIA driver stack for RTX 3090
- `/opt/stickllm/bin/llama-server` (CUDA) + `llama-server-vulkan` + `llama-server-cpu`
- Mesa Vulkan drivers / loader for AMD/Intel
- Bundled Qwen2.5 models (3B + 7B class)
- Chat UI on `:80`, llama on loopback `:8080`
- Default boot: **ephemeral** (`nopersistence`)

## Timing (rough)

| Step | Time |
|---|---|
| Model download | 5–30 min (bandwidth) |
| llama-server CUDA compile | 15–40 min |
| live-build ISO | 30–90 min |
| Output ISO size (v0.1) | ~6.5 GB (includes Q5_K_M + CUDA libs + NVIDIA) |

## Windows note

If Ubuntu WSL is broken, do not repair it just for StickLLM — use Git Bash:

`"C:\Program Files\Git\bin\bash.exe" -lc "./scripts/build.sh"`

`live-build` **must** run on a Docker named volume (`stickllm-lb-work`), not on a
OneDrive/NTFS bind mount. `scripts/build.sh` already does this. Building on the
Windows filesystem fails during debootstrap with
`Tried to extract package, but file already exists`.
