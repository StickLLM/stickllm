# StickLLM

Bootable **Privacy AI USB** — plug in, boot a locked-down Debian live environment,
chat with a local LLM from the machine or a phone on the LAN. Nothing is written
to the USB or internal disks unless you explicitly approve a write.

**Local-only inference. No cloud.**

| | |
|---|---|
| Repo | [github.com/StickLLM/stickllm](https://github.com/StickLLM/stickllm) |
| Current image | **v0.8.8** — `StickLLM-v0.8.8.iso`, hash in [`checksums/v0.8.8.sha256`](checksums/v0.8.8.sha256) (`c5aa2305…`) |
| GitHub Release | [v0.8.8](https://github.com/StickLLM/stickllm/releases/tag/v0.8.8) (ISO on Drive; checksum in git) |
| Minimum hardware | **16 GB** system RAM · **8 GB** GPU |
| GPU backends | **AMD:** ROCm and Vulkan · **NVIDIA:** CUDA · **Intel GPU:** Vulkan |
| Tested hardware | NVIDIA: single / dual RTX 3090 · AMD: single RX 570 / RX 580 — [HARDWARE.md](docs/HARDWARE.md) |
| Lab profile | AMD desktop CPU · 32 GB RAM · NVIDIA RTX 3090 (24 GB) |
| X / Twitter | [@stickllm](https://x.com/stickllm) |
| Web | [stickllm.org](https://stickllm.org) |

---

## Get StickLLM (v0.8.8)

### 1. Download

ISO is on **Google Drive** (GitHub’s 2 GB asset limit). Same folder as the older ships:

https://drive.google.com/drive/folders/1sTgvoyQi3aU-sauolWd35bKTLGynNEd-?usp=sharing

File: `StickLLM-v0.8.8.iso`

Release notes: [GitHub Release v0.8.8](https://github.com/StickLLM/stickllm/releases/tag/v0.8.8).  
The hash of record is in this repo. Check the file you download against it.

Previous published ships stay under their own names (`StickLLM-v0.8.7.iso`, older `StickLLM-v0.8.x.iso`). Do not overwrite those names. Rolling window: **N** = v0.8.8, **N-1** = v0.8.7 — see [docs/RESTORE.md](docs/RESTORE.md).

### 2. Verify checksum

**Hash of record is in this repo** — verify the Drive download against it (do not rely on a hash stored only on Drive):

[`checksums/v0.8.8.sha256`](checksums/v0.8.8.sha256)

```powershell
(Get-FileHash .\StickLLM-v0.8.8.iso -Algorithm SHA256).Hash
```

```bash
sha256sum StickLLM-v0.8.8.iso
```

### 3. Flash to USB

Flashing **erases** the stick. Pick the correct disk.

**Windows:** [Rufus](https://rufus.ie/) → select the ISO → **DD Image** mode → write → **full readback**.

**Linux:**

```bash
sudo dd if=StickLLM-v0.8.8.iso of=/dev/sdX bs=4M status=progress oflag=sync
sudo cmp -n "$(stat -c%s StickLLM-v0.8.8.iso)" StickLLM-v0.8.8.iso /dev/sdX
```

After flash, Windows often shows **no drive letter** — that is normal for this
isohybrid image. Confirm the disk with disk number / size (e.g. Get-Disk), not Explorer.

Full flash notes: [docs/FLASH.md](docs/FLASH.md). Then boot: [docs/BOOT.md](docs/BOOT.md).

---

## What's in v0.8.8

About and `stickllm.json` say **v0.8.8**. Base OS is **Debian 13 (trixie)**. Default engine remains **llama.cpp** with baked **Qwen2.5-7B Instruct Q4_K_M**. Experimental **NInfer** / Strata can be set as default on `:8080` (Confirm; switch back to llama.cpp). StickLink Method C phone join / Always-On peer remains in the shipping ISO (built from **private** StickLink sources). StickLink rendezvous/signalling remains **closed source / commercial** — see [docs/sticklink/README.md](docs/sticklink/README.md).

Highlights in this ship (ISS-065 … ISS-073):

- NInfer status accuracy (no false “loading / Downloading Qwen2.5” from parked GGUF / leftovers)
- Download to free RAM + async USB persist; RAM spike guard; Models shows Saving to USB while the durable copy finishes
- NInfer HF token for catalog pulls; Stop / Resume / Delete for NInfer queue jobs
- NInfer Context slider + Load guard (refuse when context / headroom unsafe; prefer existing tmpfs stage)
- Local timezone on first internet (geolocate public IP; not hard-locked to Eastern/UTC)

Carry from recent ships still in the ISO: USB→RAM stage before Load, NInfer Models/HF search, Agent Zero offline first-start, vault erase-in-setup, StickLink keepalive / A0 sync over phone, vision image shrink. Full list: [CHANGELOG.md](CHANGELOG.md) §0.8.8 (and §0.8.7).

**Not in the ISO:** StickDroid keep-pins APK; StickLink Worker cloud. Full CMP unlock still needs nvidia-open (this bake keeps proprietary `nvidia-kernel-dkms`).

## What's in v0.8.7 (N-1)

USB→RAM stage, NInfer Load/HF/search parity, clock NTP on Wi‑Fi, StickLink keepalive + A0 sync/vision/files. Artifact `StickLLM-v0.8.7.iso` — do not overwrite. Restore: [docs/RESTORE.md](docs/RESTORE.md).

## What’s older

Older public ships (`v0.8.6` … `v0.8.0`, `v0.4.2`, `v0.3.9`, …) may stay under their original names and checksums if still published; they are outside the N/N-1 rolling window and may be removed.

## Threat model (summary)

- Default session is **ephemeral** (RAM overlay; reboot clears chats/config).
- Inference is **local**; StickLLM web UI + pair code on LAN.
- **Persist config** and **Download model** require explicit confirmation.
- Optional encrypted SSD vault unlock from the UI (file blob; Find/Open existing after reflash) — [docs/VAULT.md](docs/VAULT.md).
- Local ≠ safe against LAN sniffers, GPU/firmware vendors, phones, or physical access.
- **Web / Tor / No internet** (taskbar Web, Settings → Network) applies to the **stick kiosk browser** and stick-local Chromium only. Paired phones and PCs on the LAN use their own network — StickLLM cannot force their traffic through Tor or offline. Details: [docs/WEB-MODE.md](docs/WEB-MODE.md).
- High-risk use: [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md).

## Runtime (on the stick)

Set firmware to **boot the USB first** ([docs/BOOT.md](docs/BOOT.md)).

| Entry | What you get |
|---|---|
| **1 Server / Local** | On-stick browser (when display present) + LAN UI. Loopback needs no pair; phone/LAN uses pair code. |
| **2 Terminal** | Console or SSH — diagnose, `stickllm-wifi-setup`, `nvidia-smi`. SSH password is **random per boot**. |
| **3 Test - SSH Enabled** | Server / Local UI + SSH. Same random SSH password on READY. |

| Endpoint | Purpose |
|---|---|
| `http://<lan-ip>/` | Chat UI (pair code on LAN) |
| `http://127.0.0.1/` | Same UI on the stick (Local trusts loopback) |
| `http://<lan-ip>/v1/chat/completions` | **Not supported** — returns **410** for third-party clients (ISS-004). Use the StickLLM UI. |

Helpers on PATH: `stickllm-status`, `stickllm-persist`, `stickllm-download-model`, `stickllm-wifi-setup`.

## Troubleshooting

**Agent Zero shows “127.0.0.1 refused to connect” (or localhost won’t connect) the first time you open it.** Agent Zero may still be starting after setup. Prefer waiting on the **Open Agent Zero** / Starting panel until it opens by itself. If the window already shows that Chromium error: use **Reload** on the desktop (right‑click the StickLLM desk → **Reload**, or press **F5**), then open **Agent Zero** again. More detail: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

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
# → out/v0.8.8/StickLLM-v0.8.8.iso  (+ SHA256SUMS; integrity-checked in-build)
```

Windows (Git Bash):

```bash
"C:\Program Files\Git\bin\bash.exe" -lc "./scripts/build.sh"
```

Full cold-start notes: [docs/BUILD.md](docs/BUILD.md). Dev loop: [docs/DEV-WORKFLOW.md](docs/DEV-WORKFLOW.md).  
Roadmap: [FEATURES.md](FEATURES.md). Vault: [docs/VAULT.md](docs/VAULT.md).  
Companion apps (planned catalog): [docs/APPS.md](docs/APPS.md).  
Troubleshooting (e.g. Agent Zero apps open in a panel, not a new tab): [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## What’s public vs maintainer-only

| Artifact | Public? |
|---|---|
| **v0.8.8** `StickLLM-v0.8.8.iso` + [`checksums/v0.8.8.sha256`](checksums/v0.8.8.sha256) | Hash is in git. ISO on [Google Drive](https://drive.google.com/drive/folders/1sTgvoyQi3aU-sauolWd35bKTLGynNEd-?usp=sharing) (GitHub’s 2 GB limit) |
| **v0.8.7** `StickLLM-v0.8.7.iso` + [`checksums/v0.8.7.sha256`](checksums/v0.8.7.sha256) | N-1 restore — same Drive folder; do not overwrite |
| Git tags `v0.8.8`, `v0.8.7`, … + checksum files in git | Yes |
| Older `StickLLM-v0.8.x.iso` / `v0.4.2` / `v0.3.9` | Drive / checksums as published — leave names alone if kept; outside rolling window |
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

StickLLM's own code is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE)
(`PolyForm-Noncommercial-1.0.0`): free for personal and other noncommercial use.
Commercial use, including selling devices that ship with StickLLM or offering paid
services based on it, needs a separate commercial license from Nink Inc. Contact via
GitHub: [github.com/StickLLM](https://github.com/StickLLM).

Bundled and downloaded third-party components (Debian/Linux, llama.cpp, Agent Zero,
NVIDIA drivers, model weights, companion apps, etc.) remain under their own licenses.

## StickLink

Rendezvous/signalling server source is private ([StickLLM/sticklink](https://github.com/StickLLM/sticklink)). Prior full monorepo history is private (StickLLM/stickllm-archive).
