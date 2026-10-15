# Building the ISO

## Cold start (from a fresh clone)

```text
1. Clone this repo
2. Install Docker Desktop (Linux containers) + Bash (Git Bash on Windows)
3. Free ~40 GB disk (models + llama builds + live-build work)
4. No prebuilt llama binaries or CUDA libs are in git — you must build them
5. Run the one-shot commands below
6. Output (v0.3.7+): out/vX.Y.Z/StickLLM-vX.Y.Z.iso
```

```bash
./scripts/verify-host.sh
./scripts/download-model.sh      # GGUF cache under models/ (gitignored)
./scripts/build-llama-server.sh  # CUDA + Vulkan + CPU llama-server in Docker
./scripts/build.sh               # Debian live-build → StickLLM-v*.iso
```

Or: `./scripts/build.sh` (calls the above as needed). Dev loop: [DEV-WORKFLOW.md](DEV-WORKFLOW.md).

Override version: `STICKLLM_VERSION=0.3.7 ./scripts/build.sh` → `out/v0.3.7/StickLLM-v0.3.7.iso`.

Builds run `scripts/lib/iso-integrity-check.sh` inside Docker so truncated hybrids fail before publish. On Windows hosts, `xorriso` is usually absent — re-check with Docker if you need a second pass:

```bash
docker run --rm -v "$PWD/scripts/lib/iso-integrity-check.sh:/check.sh:ro" \
  -v "$PWD/out/v0.3.7:/iso:ro" debian:bookworm \
  bash -c 'apt-get update -qq && apt-get install -y -qq xorriso >/dev/null && bash /check.sh /iso/StickLLM-v0.3.7.iso'
```
That check needs `xorriso`; on Windows/Git Bash (no host xorriso) it uses Docker
automatically — same Docker dependency as the build itself.

## ISO filename convention

| Era | Pattern | Example |
|-----|---------|---------|
| **v0.3.7+** (new ships) | `StickLLM-vX.Y.Z.iso` | `StickLLM-v0.3.7.iso` |
| Through **v0.3.6** (historical) | `stickllm-amd-rtx3090-v….hybrid.iso` | `stickllm-amd-rtx3090-v0.3.6.hybrid.iso` |

Default for current amd64 ships: **exactly** `StickLLM-vX.Y.Z.iso` — no `.hybrid`, no GPU/profile/arch segment. Add an arch/variant suffix only when shipping a distinct platform later (e.g. `StickLLM-vX.Y.Z-arm64.iso`). Do **not** rename or rewrite already-shipped artifacts (v0.3.6 and earlier stay under their old names/checksums).

## Host requirements

- **Docker** (required for live-build / llama compile)
- Bash (Git Bash on Windows, or Linux/macOS)
- **~40 GB** free disk
- Network (Debian packages, CUDA devel image, GGUF download)

WSL2 Ubuntu is optional. On Windows the preferred path is **Git Bash + Docker Desktop**.

## What the ISO contains

- Debian Bookworm live (UEFI hybrid)
- Proprietary NVIDIA driver stack for RTX 3090
- `/opt/stickllm/bin/llama-server` (CUDA) + `llama-server-vulkan` + `llama-server-cpu`
- Mesa Vulkan drivers / loader for AMD/Intel
- Bundled Qwen2.5 models (3B + 7B class through v0.3.8; next ship: 3B only — ISS-020)
- Chat UI on `:80`, llama on loopback `:8080`
- Default boot: **ephemeral** (`nopersistence`)

## Timing (rough)

| Step | Time |
|---|---|
| Model download | 5–30 min (bandwidth) |
| llama-server CUDA compile | 15–40 min |
| live-build ISO | 30–90 min |
| Output ISO size | ~6–8 GB class |

## Windows note

If Ubuntu WSL is broken, do not repair it just for StickLLM — use Git Bash:

`"C:\Program Files\Git\bin\bash.exe" -lc "./scripts/build.sh"`

`live-build` **must** run on a Docker named volume (`stickllm-lb-work`), not on a
OneDrive/NTFS bind mount. `scripts/build.sh` already does this. Building on the
Windows filesystem fails during debootstrap with
`Tried to extract package, but file already exists`.
