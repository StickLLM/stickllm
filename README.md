# StickLLM

Bootable **Privacy AI USB** — plug in, boot a locked-down Debian live environment,
chat with a local LLM from the machine or a phone on the LAN. Nothing is written
to the USB or internal disks unless you explicitly approve a write.

**Consumer intent:** local-only inference. No cloud.

| | |
|---|---|
| Repo | [github.com/StickLLM/stickllm](https://github.com/StickLLM/stickllm) |
| Shipping | **v0.2.0** (Drive / Samsung golden) |
| Checkpoint | **v0.2.1-local-nvidia-kbd** (Local browser + keyboard on NVIDIA) |
| Profile | **AMD desktop CPU · 32 GB RAM · NVIDIA RTX 3090 (24 GB)** |
| Release | [v0.2.0](https://github.com/StickLLM/stickllm/releases/tag/v0.2.0) |
| X / Twitter | [@stickllm](https://x.com/stickllm) |
| Web | [stickllm.org](https://stickllm.org) |

## Shipping vs checkpoint

| | Drive golden **v0.2.0** | Checkpoint **v0.2.1-local-nvidia-kbd** |
|---|---|---|
| Tag | [`v0.2.0`](https://github.com/StickLLM/stickllm/releases/tag/v0.2.0) (`c63fadc`) | [`v0.2.1-local-nvidia-kbd`](https://github.com/StickLLM/stickllm/releases/tag/v0.2.1-local-nvidia-kbd) |
| ISO | `stickllm-amd-rtx3090-v0.2.hybrid.iso` (Google Drive) | `out/v0.2.1-local-nvidia-kbd/stickllm-amd-rtx3090-v0.2-local-nvidia-kbd.hybrid.iso` |
| SHA-256 | [`checksums/v0.2.sha256`](checksums/v0.2.sha256) → `4914087d…` | [`checksums/v0.2-local-nvidia-kbd.sha256`](checksums/v0.2-local-nvidia-kbd.sha256) → `9F665ACA…` |
| Role | Immutable ship — **do not overwrite** | Restore point for Local cage + Chromium + keyboard |

Golden baseline details: [docs/BASELINE-v0.2.md](docs/BASELINE-v0.2.md). Roadmap: [FEATURES.md](FEATURES.md).

## Download golden v0.2 ISO

ISO is on **Google Drive** (GitHub asset limit is 2 GB):  
https://drive.google.com/drive/folders/1sTgvoyQi3aU-sauolWd35bKTLGynNEd-?usp=sharing  

File: `stickllm-amd-rtx3090-v0.2.hybrid.iso`

```powershell
(Get-FileHash .\stickllm-amd-rtx3090-v0.2.hybrid.iso -Algorithm SHA256).Hash
# expect 4914087D502D13327DBBD9196C9A4A7DF46EE079D423FF4B0BC6280E1C7B1A48
```

## Restore the Local checkpoint

```text
ISO:      out/v0.2.1-local-nvidia-kbd/stickllm-amd-rtx3090-v0.2-local-nvidia-kbd.hybrid.iso
Checksum: checksums/v0.2-local-nvidia-kbd.sha256
          (same digest as out/v0.2.1-local-nvidia-kbd/v0.2-local-nvidia-kbd.sha256)
Tag:      git checkout v0.2.1-local-nvidia-kbd
```

```powershell
(Get-FileHash .\out\v0.2.1-local-nvidia-kbd\stickllm-amd-rtx3090-v0.2-local-nvidia-kbd.hybrid.iso -Algorithm SHA256).Hash
# expect 9F665ACAA0D60B9DE822781A3A3A3F56C6C4924536E677599C09DBC8D339A1FC
```

## Threat model (summary)

- Default session is **ephemeral** (RAM overlay; reboot clears chats/config).
- Inference is **local**; UI/API are **LAN HTTP + pair code** (TLS later) — no cloud API.
- **Persist config** and **Download model** require explicit confirmation.
- Local ≠ safe against LAN sniffers, GPU/firmware vendors, phones, or physical access.
- **Journalists / gov / high-risk:** [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md).

## Folder layout

```
stickllm/
├── config/profiles/amd-rtx3090.toml   # sole supported host profile
├── docs/                              # flash, boot, hardware, threat model
├── FEATURES.md                        # working vs planned roadmap
├── ui/                                # StickLLM chat UI (HTTP :80)
├── overlay/                           # files copied into the live rootfs
├── live-build/                        # Debian live-build hooks & package lists
├── scripts/                           # build, model fetch, flash helpers
├── checksums/                         # published ISO digests (in git)
├── models/                            # GGUF cache (not in git)
└── out/                               # ISO output (not in git)
```

## Build toolchain

| Piece | Choice |
|---|---|
| Live OS | Debian Bookworm via **live-build** |
| Reproducible host | **Docker** (preferred) or **WSL2 Ubuntu** |
| GPU | Proprietary **NVIDIA** driver (CUDA path for 3090) |
| Inference | **llama.cpp** `llama-server` (OpenAI-compatible HTTP) |
| Models | **On ISO:** small text models (3B + 7B class). **Download to DATA:** larger (e.g. 27B) when VRAM + free space allow. Catalog SHA-256 on USB. Optional DuckDuckGo via gateway |
| UI | Native StickLLM UI on :80 → gateway → llama :8080 |
| Persistence | Off by default; explicit tools only |

```bash
# On Linux or WSL2 (Docker recommended)
./scripts/verify-host.sh
./scripts/download-model.sh
./scripts/build.sh                   # produces a hybrid ISO under out/
```

Build: [docs/BUILD.md](docs/BUILD.md) · Flash: [docs/FLASH.md](docs/FLASH.md) ·
Boot: [docs/BOOT.md](docs/BOOT.md) · Hardware: [docs/HARDWARE.md](docs/HARDWARE.md) ·
Models: [docs/MODELS.md](docs/MODELS.md)

## Runtime (on the stick)

Set the PC firmware to **boot the USB first** (see [docs/BOOT.md](docs/BOOT.md)).

| Entry | What you get |
|---|---|
| **1 StickLLM Server** | Console READY + pair code; phone/LAN browser chat over **HTTP**. |
| **2 StickLLM Local** | Same-box **cage + Chromium** on the NVIDIA HDMI path (checkpoint). Keyboard via DRM + libinput. Loopback UI; no pair on this box. |
| **3 StickLLM Term** | Console login or `ssh user@<ip>` (password `stickllm`) — `nvidia-smi`, etc. |
| **4 StickLLM Failsafe** | No NVIDIA — recover from GPU/black-screen hangs (Term/SSH only). |

| Endpoint | Purpose |
|---|---|
| `http://<lan-ip>/` | Chat UI (pair code on LAN) |
| `http://127.0.0.1/` | Same UI on the stick (Local trusts loopback) |
| `http://<lan-ip>/v1/chat/completions` | OpenAI-compatible API (gateway; pair Bearer required) |
| `http://<lan-ip>:8080/v1/*` | Raw llama.cpp (no pair auth; no web lookup) |

After pairing, **Models → API key** shows the session token until reboot.

Helpers on PATH: `stickllm-status`, `stickllm-persist`, `stickllm-download-model`, `stickllm-local-chat`.

### Local (NVIDIA) notes — checkpoint

Working on RTX 3090 HDMI with tag `v0.2.1-local-nvidia-kbd`:

- Boot keeps `nvidia-drm.modeset=0` so the console/HDMI path stays alive.
- Local enables NVIDIA KMS **at runtime** for cage/Chromium (do **not** force modeset=1 on the kernel cmdline for all modes — that blanks HDMI).
- Real hardware kiosk input: `WLR_BACKENDS=drm,libinput`. Never set `WLR_LIBINPUT_NO_DEVICES=1` on hardware (QEMU proofs only).

## Working today (checkpoint)

- Boot menu: Local / Server / Term (+ Failsafe)
- Pair code → browser chat + Models menu; session token = API key
- Term/Server LAN READY + pair + URL
- Local cage + Chromium + keyboard on NVIDIA DRM
- USB DATA claim; catalog downloads (27B → DATA when pinned/space allows)
- Ephemeral by default

## Later

See [FEATURES.md](FEATURES.md). High level: TLS, keyboard-only UI nav, signed catalog, vault, client stick, AMD/Intel profiles, Tor, Secure Boot.

## License

MIT — see [LICENSE](LICENSE). Third-party model weights and NVIDIA drivers remain
under their own licenses; the build scripts download them separately.
