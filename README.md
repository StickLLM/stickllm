# StickLLM

Bootable **Privacy AI USB** — plug in, boot a locked-down Debian live environment,
chat with a local LLM from the machine or a phone on the LAN. Nothing is written
to the USB or internal disks unless you explicitly approve a write.

**Local-only inference. No cloud.**

| | |
|---|---|
| Repo | [github.com/StickLLM/stickllm](https://github.com/StickLLM/stickllm) |
| Current image | **v0.4.2** — `StickLLM-v0.4.2.iso`, hash in [`checksums/v0.4.2.sha256`](checksums/v0.4.2.sha256) |
| Last GitHub Release | **[v0.3.9](https://github.com/StickLLM/stickllm/releases/tag/v0.3.9)** |
| Profile | AMD desktop CPU · 32 GB RAM · NVIDIA RTX 3090 (24 GB) |
| X / Twitter | [@stickllm](https://x.com/stickllm) |
| Web | [stickllm.org](https://stickllm.org) |

---

## Get StickLLM (v0.4.2)

### 1. Download

ISO is on **Google Drive** (GitHub’s 2 GB asset limit). Same folder as the older ships:

https://drive.google.com/drive/folders/1sTgvoyQi3aU-sauolWd35bKTLGynNEd-?usp=sharing

File: `StickLLM-v0.4.2.iso`

The hash of record is in this repo. Check the file you download against it. An older local build of this same name used hash `f31b5353280a2fd67734818cea2d76ecaf5e5281f27295ffa79a54bbca270875` — do not publish that file.

Previous published ship stays `StickLLM-v0.3.9.iso` (hash `32a37a66…`). `StickLLM-v0.3.8.iso` (hash `88f78154…`) stays available too.

### 2. Verify checksum

**Hash of record is in this repo** — verify the Drive download against it (do not rely on a hash stored only on Drive):

[`checksums/v0.4.2.sha256`](checksums/v0.4.2.sha256)

```powershell
(Get-FileHash .\StickLLM-v0.4.2.iso -Algorithm SHA256).Hash
# expect 3A50EB56A7D2FC4E6A55AABFCCC0971E38DDE2B5560BE3B6892FA6AA38572EF7
```

```bash
sha256sum StickLLM-v0.4.2.iso
# expect 3a50eb56a7d2fc4e6a55aabfccc0971e38dde2b5560be3b6892fa6aa38572ef7
```

### 3. Flash to USB

Flashing **erases** the stick. Pick the correct disk.

**Windows:** [Rufus](https://rufus.ie/) → select the ISO → **DD Image** mode → write.

**Linux:**

```bash
sudo dd if=StickLLM-v0.4.2.iso of=/dev/sdX bs=4M status=progress oflag=sync
```

After flash, Windows often shows **no drive letter** — that is normal for this
isohybrid image. Confirm the disk with disk number / size (e.g. Get-Disk), not Explorer.

Full flash notes: [docs/FLASH.md](docs/FLASH.md). Then boot: [docs/BOOT.md](docs/BOOT.md).

---

## What’s in v0.4.2

About and `stickllm.json` say **v0.4.2**. This image keeps the v0.3.9 chat stick (3B baked, 7B download-only, pair code, ephemeral session, SSD vault file) and adds:

- **Voice** on/off. Whisper (tiny.en) and KittenTTS (mini 0.8, Bella) stay resident. Replies stream, and a stop button cuts speech off. While Voice is on, the reply is capped at 80 tokens, a short spoken-style instruction is added without showing it in the thread, and thinking text is skipped. After real speech, one second of silence sends the line.
- **Vault chat delete** removes that saved chat.
- **USB settings partition.** First boot reserves about 256 MB raw on the stick, beside the live image, and does not shrink an existing `STICKLLM-DATA`. The partition is formatted when the vault is unlocked, with the same passcode. Opening a vault that is already on the SSD is unchanged: [Opening an existing vault](docs/VAULT.md#opening-an-existing-vault).
- **Load.** The status poll does not paint Loading until the browser is paired. The load meter starts at 1% and does not jump to a fake 30%.

Speech weights and `whisper-server` are baked at image build. They are not downloaded on the stick and they are not stored in the vault.

## What’s in v0.3.9

- Built-in model is **Qwen2.5 3B** only. **Qwen2.5 7B** is download-only (it is not in the ISO).
- Hugging Face search, including uncensored/abliterated, and a one-at-a-time download queue with stop, start, and delete. The queue is saved in the models folder and resumes after reboot.
- Fit labels use the combined VRAM of the suitable GPUs.
- Chat footer shows speed and how much of the loaded context the reply used.
- Boot: **Local/Server**, **Terminal**, **Test - SSH Enabled**
- Inference: **CUDA → Vulkan → CPU** fallback
- Kiosk chat UI on `:80`; LAN pair code (loopback needs no pair; **F9** remints PAIR CODE on kiosk)
- Ephemeral by default; optional encrypted SSD vault unlock from the UI (file blob; Find/Open existing after reflash)
- Mount host drives; claim stick free space for durable downloads
- llama on **127.0.0.1:8080** only
- **StickLLM UI only** — external OpenAI-style `/v1` clients get **410** (see [FEATURES.md](FEATURES.md))

Release notes: [GitHub Release v0.3.9](https://github.com/StickLLM/stickllm/releases/tag/v0.3.9).

## What’s in v0.3.8

Previous ship (~8.7 GB), still recoverable. It baked both the 3B and the 7B. Notes: [GitHub Release v0.3.8](https://github.com/StickLLM/stickllm/releases/tag/v0.3.8).

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
| **2 Terminal** | Console or SSH — diagnose, `stickllm-wifi-setup`, `nvidia-smi`. SSH password is **random per boot**. |
| **3 Test - SSH Enabled** | Server / Local UI + SSH. Same random SSH password on READY. |

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
# → out/v0.4.2/StickLLM-v0.4.2.iso  (+ SHA256SUMS; integrity-checked in-build)
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
| **v0.4.2** `StickLLM-v0.4.2.iso` + [`checksums/v0.4.2.sha256`](checksums/v0.4.2.sha256) | Hash is in git. The ISO is not (GitHub’s 2 GB limit). Put that file on the Drive folder and check it against the digest |
| **v0.3.9** ISO on Google Drive + [`checksums/v0.3.9.sha256`](checksums/v0.3.9.sha256) | Yes — previous published ship |
| **v0.3.8** ISO on Google Drive + [`checksums/v0.3.8.sha256`](checksums/v0.3.8.sha256) | Yes — older published ship |
| Git tags `v0.3.9`, `v0.3.8`, `v0.3.6`, `v0.2.0` + checksum files in git | Yes |
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
