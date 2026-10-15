# StickLLM

Bootable **Privacy AI USB** — plug in, boot a locked-down Debian live environment,
chat with a local LLM from the machine or a phone on the LAN. Nothing is written
to the USB or internal disks unless you explicitly approve a write.

**Consumer intent:** local-only inference. No cloud.

| | |
|---|---|
| Repo | [github.com/StickLLM/stickllm](https://github.com/StickLLM/stickllm) |
| Drive golden (forever) | **v0.2.0** (Samsung — immutable) |
| Current ship (**N**) | **v0.3.6** (encrypted SSD vault + ISO integrity check; Drive) |
| Previous ship (**N-1**) | **v0.3.0** (apiready) |
| Checkpoint | **v0.2.1-local-nvidia-kbd** (Local browser + keyboard on NVIDIA; outside N window) |
| Profile | **AMD desktop CPU · 32 GB RAM · NVIDIA RTX 3090 (24 GB)** |
| Release | [v0.2.0](https://github.com/StickLLM/stickllm/releases/tag/v0.2.0) · [v0.3.0](https://github.com/StickLLM/stickllm/releases/tag/v0.3.0) · [v0.3.6](https://github.com/StickLLM/stickllm/releases/tag/v0.3.6) |
| X / Twitter | [@stickllm](https://x.com/stickllm) |
| Web | [stickllm.org](https://stickllm.org) |

## Shipping vs N-2 restore

Keep the **last two recoverable ships** (N and N-1) plus the Drive golden forever. Details: [docs/RESTORE.md](docs/RESTORE.md).

| | Drive golden **v0.2.0** | **N-1** `v0.3.0` | **N** `v0.3.6` |
|---|---|---|---|
| Tag | [`v0.2.0`](https://github.com/StickLLM/stickllm/releases/tag/v0.2.0) | [`v0.3.0`](https://github.com/StickLLM/stickllm/releases/tag/v0.3.0) | [`v0.3.6`](https://github.com/StickLLM/stickllm/releases/tag/v0.3.6) |
| ISO | Drive `stickllm-amd-rtx3090-v0.2.hybrid.iso` | `out/v0.3.0/…v0.3-apiready.hybrid.iso` | Drive / `out/v0.3.6/…v0.3.6.hybrid.iso` |
| SHA-256 | [`checksums/v0.2.sha256`](checksums/v0.2.sha256) → `4914087d…` | [`checksums/v0.3.sha256`](checksums/v0.3.sha256) → `f3db9113…` | [`checksums/v0.3.6.sha256`](checksums/v0.3.6.sha256) → `fb559d9f…` |
| Role | Immutable forever | Previous ship — do not delete when cutting v0.4 | Current ship |

When cutting **v0.4+**: new tag + new `out/<version>/StickLLM-vX.Y.Z.iso` + new checksum; **never** delete N/N-1 tags or ISO dirs; **never** overwrite Drive `v0.2.0` or Drive `v0.3.6` under the same name. Through **v0.3.6**, ISO files keep the historical `stickllm-amd-rtx3090-v….hybrid.iso` names; newer ships use exactly `StickLLM-vX.Y.Z.iso` (example: `StickLLM-v0.3.7.iso`; see [docs/BUILD.md](docs/BUILD.md)).

**Do not flash `v0.3.5`** — truncated/broken ISO. Use **v0.3.6**.

Golden baseline: [docs/BASELINE-v0.2.md](docs/BASELINE-v0.2.md). Roadmap: [FEATURES.md](FEATURES.md). Issues: [ISSUES.md](ISSUES.md). Vault: [docs/VAULT.md](docs/VAULT.md). Flash: [docs/FLASH.md](docs/FLASH.md).

## Download current ship v0.3.6

ISO is on **Google Drive** (GitHub asset limit is 2 GB) — same StickLLM-releases folder as v0.2:  
https://drive.google.com/drive/folders/1sTgvoyQi3aU-sauolWd35bKTLGynNEd-?usp=sharing  

File: `stickllm-amd-rtx3090-v0.3.6.hybrid.iso`  
Checksum: [`checksums/v0.3.6.sha256`](checksums/v0.3.6.sha256) · Tag: `git checkout v0.3.6`

```powershell
(Get-FileHash .\stickllm-amd-rtx3090-v0.3.6.hybrid.iso -Algorithm SHA256).Hash
# expect FB559D9F0CC5182406F0851F09C1E28C302F911C01B46CAC545EF4D920E1A43D
```

Windows flash: elevated `out/safe-flash-samsung-auth.py` (or Rufus DD). No drive letter after isohybrid is normal — confirm the disk with Get-Disk, not Explorer.

## Download Drive golden v0.2 ISO

Same Google Drive folder. File: `stickllm-amd-rtx3090-v0.2.hybrid.iso`

```powershell
(Get-FileHash .\stickllm-amd-rtx3090-v0.2.hybrid.iso -Algorithm SHA256).Hash
# expect 4914087D502D13327DBBD9196C9A4A7DF46EE079D423FF4B0BC6280E1C7B1A48
```

## Restore N-1 (v0.3.0)

```text
ISO:      out/v0.3.0/stickllm-amd-rtx3090-v0.3-apiready.hybrid.iso
Checksum: checksums/v0.3.sha256
Tag:      git checkout v0.3.0
```

```powershell
(Get-FileHash .\out\v0.3.0\stickllm-amd-rtx3090-v0.3-apiready.hybrid.iso -Algorithm SHA256).Hash
# expect F3DB91133AE6FD1CAACAFD385A61DA6949064F32AC60045378BE4D69441FC218
```

## v0.3.6 notes

- Encrypted SSD vault (file blob only; Find/Open existing after reflash); ISO integrity check before ship; Windows safe-flash path documented.
- llama binds **127.0.0.1:8080** only; CUDA → Vulkan → CPU backends; StickLLM UI only (no external OpenAI LAN API).
- **Does not** overwrite Drive golden v0.2. See [ISSUES.md](ISSUES.md) / [FEATURES.md](FEATURES.md).

## Threat model (summary)

- Default session is **ephemeral** (RAM overlay; reboot clears chats/config).
- Inference is **local**; StickLLM web UI + pair code on LAN (no third-party OpenAI API).
- **Persist config** and **Download model** require explicit confirmation.
- Local ≠ safe against LAN sniffers, GPU/firmware vendors, phones, or physical access.
- **Journalists / gov / high-risk:** [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md).

## Folder layout

```
stickllm/
├── config/profiles/amd-rtx3090.toml   # sole supported host profile
├── docs/                              # flash, boot, hardware, threat model
├── FEATURES.md                        # working vs planned roadmap
├── ISSUES.md                          # open product/bug log
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

**Dev loop:** feature branch → SSH-test on a running stick → one clean ISO when
the batch is done (never patch ISO) → user HW confirm before tag/push.
See [docs/DEV-WORKFLOW.md](docs/DEV-WORKFLOW.md).

Build: [docs/BUILD.md](docs/BUILD.md) · Flash: [docs/FLASH.md](docs/FLASH.md) ·
Boot: [docs/BOOT.md](docs/BOOT.md) · Hardware: [docs/HARDWARE.md](docs/HARDWARE.md) ·
Models: [docs/MODELS.md](docs/MODELS.md)

## Runtime (on the stick)

Set the PC firmware to **boot the USB first** (see [docs/BOOT.md](docs/BOOT.md)).

| Entry | What you get |
|---|---|
| **1 Server / Local** | On-stick browser (when display present) + LAN UI. Loopback needs no pair; phone/LAN uses pair code. Status banner shows pair / IP / model / URL. |
| **2 Secure Client** | Coming later (menu stub). |
| **3 Terminal** | Console (tty2) or SSH — diagnose, `stickllm-wifi-setup`, `nvidia-smi`. SSH password is **random per boot** (shown on console). |
| **4 Test** | Server / Local UI + SSH (`stickllm.chat stickllm.ssh`). Same random SSH password on READY. |

### WiFi (Server / Term / Local)

| Situation | What to do |
|---|---|
| Stick already has LAN (Ethernet or saved WiFi) | Browser → **Settings → Network** (after Pair on Server/Term; Local needs no pair) |
| Server/Term with **no** uplink (no Ethernet) | `Ctrl+Alt+F2` → login `user` / `stickllm` → run **`stickllm-wifi-setup`** (scan + password). Same NM profile as the web form. |
| Alternate bootstrap | Boot **Local** once, connect WiFi (saves on DATA when claimed), reboot into Server; or plug Ethernet once, then Settings → Network |
| Not yet | Temporary setup AP — Settings stub only |

| Endpoint | Purpose |
|---|---|
| `http://<lan-ip>/` | Chat UI (pair code on LAN) |
| `http://127.0.0.1/` | Same UI on the stick (Local trusts loopback) |
| `http://<lan-ip>/v1/chat/completions` | OpenAI-compatible API (gateway; pair Bearer required). **Present on current flash; deprecated — going away next version** (ISS-004: StickLLM UI only; no external clients). |
| `http://<lan-ip>:8080/v1/*` | Raw llama.cpp (no pair auth; no web lookup). Not a supported product surface for apps. |

**Models** = catalog / download / activate / delete. **Settings** = Network/WiFi, claim USB, future stubs (context, SSD vault). Local hides the Pair button.

Helpers on PATH: `stickllm-status`, `stickllm-persist`, `stickllm-download-model`, `stickllm-local-chat`, `stickllm-wifi-setup`, `stickllm-wifi-apply`.

### Local (NVIDIA) notes — checkpoint

Working on RTX 3090 HDMI with tag `v0.2.1-local-nvidia-kbd`:

- Boot keeps `nvidia-drm.modeset=0` so the console/HDMI path stays alive.
- Local enables NVIDIA KMS **at runtime** for cage/Chromium (do **not** force modeset=1 on the kernel cmdline for all modes — that blanks HDMI).
- Real hardware kiosk input: `WLR_BACKENDS=drm,libinput`. Never set `WLR_LIBINPUT_NO_DEVICES=1` on hardware (QEMU proofs only).

## Working today (checkpoint)

- Boot menu: Server / Local, Secure Client, Terminal, Test
- Pair code → browser chat (Local: no pair chrome); Models + Settings menus
- Term/Server LAN READY + pair + URL; console `stickllm-wifi-setup` when no uplink
- Local cage + Chromium + keyboard on NVIDIA DRM
- USB DATA claim; catalog downloads (27B → DATA when pinned/space allows)
- Ephemeral by default

## Later

See [FEATURES.md](FEATURES.md). High level: TLS, keyboard-only UI nav, signed catalog, vault, client stick, AMD/Intel profiles, Tor, Secure Boot.

## License

MIT — see [LICENSE](LICENSE). Third-party model weights and NVIDIA drivers remain
under their own licenses; the build scripts download them separately.
