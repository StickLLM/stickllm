# StickLLM

Bootable **Privacy AI USB** — plug in, boot a locked-down Debian live environment,
chat with a local LLM from the machine or a phone on the LAN. Nothing is written
to the USB or internal disks unless you explicitly approve a write.

**Local-only inference. No cloud.**

| | |
|---|---|
| Repo | [github.com/StickLLM/stickllm](https://github.com/StickLLM/stickllm) |
| Current release | **[v0.3.6](https://github.com/StickLLM/stickllm/releases/tag/v0.3.6)** |
| Profile | AMD desktop CPU · 32 GB RAM · NVIDIA RTX 3090 (24 GB) |
| X / Twitter | [@stickllm](https://x.com/stickllm) |
| Web | [stickllm.org](https://stickllm.org) |

---

## Get StickLLM (v0.3.6)

### 1. Download

ISO (~7 GB) is on **Google Drive** (GitHub’s 2 GB asset limit):

https://drive.google.com/drive/folders/1sTgvoyQi3aU-sauolWd35bKTLGynNEd-?usp=sharing

File: `stickllm-amd-rtx3090-v0.3.6.hybrid.iso`

**Do not use v0.3.5** — that ISO is truncated/broken.

### 2. Verify checksum

File in this repo: [`checksums/v0.3.6.sha256`](checksums/v0.3.6.sha256)

```powershell
(Get-FileHash .\stickllm-amd-rtx3090-v0.3.6.hybrid.iso -Algorithm SHA256).Hash
# expect FB559D9F0CC5182406F0851F09C1E28C302F911C01B46CAC545EF4D920E1A43D
```

```bash
sha256sum stickllm-amd-rtx3090-v0.3.6.hybrid.iso
# expect fb559d9f0cc5182406f0851f09c1e28c302f911c01b46cac545ef4d920e1a43d
```

### 3. Flash to USB

Flashing **erases** the stick. Pick the correct disk.

**Windows:** [Rufus](https://rufus.ie/) → select the ISO → **DD Image** mode → write.

**Linux:**

```bash
sudo dd if=stickllm-amd-rtx3090-v0.3.6.hybrid.iso of=/dev/sdX bs=4M status=progress oflag=sync
```

After flash, Windows often shows **no drive letter** — that is normal for this
isohybrid image. Confirm the disk with disk number / size (e.g. Get-Disk), not Explorer.

Full flash notes: [docs/FLASH.md](docs/FLASH.md). Then boot: [docs/BOOT.md](docs/BOOT.md).

---

## What’s in v0.3.6

- Encrypted SSD vault (file blob only; Find/Open existing after reflash)
- StickLLM chat UI on `:80` (pair code on LAN; loopback needs no pair)
- llama on **127.0.0.1:8080** only; backends CUDA → Vulkan → CPU
- **StickLLM UI only** — external OpenAI-style `/v1` clients get **410** (see [FEATURES.md](FEATURES.md))

Release notes: [GitHub Release v0.3.6](https://github.com/StickLLM/stickllm/releases/tag/v0.3.6).

## Threat model (summary)

- Default session is **ephemeral** (RAM overlay; reboot clears chats/config).
- Inference is **local**; StickLLM web UI + pair code on LAN.
- **Persist config** and **Download model** require explicit confirmation.
- Local ≠ safe against LAN sniffers, GPU/firmware vendors, phones, or physical access.
- High-risk use: [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md).

## Runtime (on the stick)

Set firmware to **boot the USB first** ([docs/BOOT.md](docs/BOOT.md)).

| Entry | What you get |
|---|---|
| **1 Server / Local** | On-stick browser (when display present) + LAN UI. Loopback needs no pair; phone/LAN uses pair code. |
| **2 Secure Client** | Coming later (menu stub). |
| **3 Terminal** | Console or SSH — diagnose, `stickllm-wifi-setup`, `nvidia-smi`. SSH password is **random per boot**. |
| **4 Test** | Server / Local UI + SSH. Same random SSH password on READY. |

| Endpoint | Purpose |
|---|---|
| `http://<lan-ip>/` | Chat UI (pair code on LAN) |
| `http://127.0.0.1/` | Same UI on the stick (Local trusts loopback) |
| `http://<lan-ip>/v1/chat/completions` | **Not supported** — returns **410** for third-party clients (ISS-004). Use the StickLLM UI. |

Helpers on PATH: `stickllm-status`, `stickllm-persist`, `stickllm-download-model`, `stickllm-wifi-setup`.

## Build from source (first-class)

Anyone can clone this repo and produce a bootable ISO. Prebuilt llama/CUDA
binaries are **not** in git — the scripts download models and compile
`llama-server` in Docker.

**Needs:** Docker Desktop (Linux containers), Bash (Git Bash on Windows),
**~40 GB** free disk, network. First bake often takes 1–3 hours.

```bash
git clone https://github.com/StickLLM/stickllm.git
cd stickllm
./scripts/verify-host.sh
./scripts/download-model.sh
./scripts/build-llama-server.sh
./scripts/build.sh
# → out/v0.3.7/StickLLM-v0.3.7.iso  (+ SHA256SUMS; integrity-checked in-build)
```

Windows (Git Bash):

```bash
"C:\Program Files\Git\bin\bash.exe" -lc "./scripts/build.sh"
```

Full cold-start notes: [docs/BUILD.md](docs/BUILD.md). Dev loop: [docs/DEV-WORKFLOW.md](docs/DEV-WORKFLOW.md).  
Roadmap: [FEATURES.md](FEATURES.md). Vault: [docs/VAULT.md](docs/VAULT.md).

## What’s public vs maintainer-only

| Artifact | Public? |
|---|---|
| **v0.3.6** ISO on Google Drive + [`checksums/v0.3.6.sha256`](checksums/v0.3.6.sha256) | Yes — current ship |
| Git tags `v0.3.6`, `v0.3.0`, `v0.2.0` + checksum files in git | Yes |
| **v0.2.0** GitHub Release (split `.7z` + Drive link) | Yes — older golden |
| `out/v0.3.0/…` apiready ISO | **No** — local/maintainer restore only |
| Maintainer Windows Python flasher, ISO-READY gates, lab hardware notes | [docs/MAINTAINER.md](docs/MAINTAINER.md) |

Restore policy: [docs/RESTORE.md](docs/RESTORE.md).

## Maintainers

Dev loop, SSH iterate, release bake: [docs/DEV-WORKFLOW.md](docs/DEV-WORKFLOW.md).  
Maintainer flash / lab notes: [docs/MAINTAINER.md](docs/MAINTAINER.md).  
Contributing pointers: [CONTRIBUTING.md](CONTRIBUTING.md).

## Folder layout

```
stickllm/
├── config/profiles/amd-rtx3090.toml   # sole supported host profile
├── docs/                              # flash, boot, build, threat model
├── FEATURES.md                        # working vs planned
├── ISSUES.md                          # open product/bug log
├── ui/                                # StickLLM chat UI (HTTP :80)
├── overlay/                           # files copied into the live rootfs
├── live-build/                        # Debian live-build hooks & package lists
├── scripts/                           # build, model fetch, flash helpers
├── checksums/                         # published ISO digests (in git)
├── models/                            # GGUF cache (not in git)
└── out/                               # ISO output (not in git)
```

## License

MIT — see [LICENSE](LICENSE). Third-party model weights and NVIDIA drivers remain
under their own licenses; the build scripts download them separately.
