# StickLLM Features

Legend: [x] working today, [ ] planned. Priority: P0 = next, P1 = soon, P2 = later.

The high-level idea list and the checklist below are one plan (2026-10-16). Security architecture is parked until the working product is settled. Do not start NINO, the client-stick lockdown, zero-trust remote access, or signed multi-signer updates before then.

**Next (P0):** finish Models, then wire the greyed Advanced controls (ISS-021). Hugging Face search, the download queue, hash checks, and VRAM fit labels already ship. Still open: the same filters when choosing an installed model to load, and the Advanced knobs that are on screen but not applied (temperature, top-p, top-k, repeat penalty, max reply tokens, KV cache type, backend). AMD and Intel coverage stays on the hardware list after that.

## Ideas

Working today:

- Boot menu: Local / Server (GPU chat or share on the LAN), Terminal, Test (SSH enabled for maintainers)
- NVIDIA CUDA acceleration, with Vulkan and CPU fallback
- Built-in small model (3B), plus downloadable larger models from Settings
- Kiosk chat UI (desktop and phone browser), pair on the LAN with a one-time code
- Ephemeral by default: reboot clears the session
- Optional encrypted vault unlock from the UI for saved storage (saved chats already live here, and a saved chat can be deleted)
- About 256 MB USB settings partition: raw on first boot, formatted with the vault passcode on unlock
- Voice on/off: resident Whisper and Kitten, streaming speech, stop button, one-second silence sends after real speech
- Mount host drives or claim free space on the StickLLM stick
- Model selection, download, and verification from Hugging Face
- Shipping ISOs as `StickLLM-vX.Y.Z.iso` (flash with Rufus DD Image, or build from source)

Still to build, in order. Each line points at the checklist section that owns it:

1. **Next.** Finish model filters on installed models, and wire the greyed Advanced section — Models, Settings
2. Stronger AMD / Intel GPU paths and broader hardware coverage — Boot and hardware
3. Rest of the vault story: stick key + PIN. The 12-word recovery phrase already exists. Panic / duress PIN stays parked — Vault and security. The 256 MB USB settings partition ships in v0.4.2 (raw on first boot, same vault passcode on unlock)
4. Saved settings and per-model presets (saved chats already exist) — Settings
5. Vision (image input) and document RAG — Chats and documents. Voice chat ships in v0.4.2
6. Agent voice (wake word) — chat Voice on/off, streaming speech, and read-aloud ship in v0.4.2; see Companion apps
7. Agent Zero, installable — Companion apps
8. Apps from a catalog, for a person or an agent — [docs/APPS.md](docs/APPS.md)

Parked with security (do not build yet):

- Dedicated client stick paired with a server stick — Client and networking
- Mobile apps (iOS, Android, GrapheneOS) with QR pairing and authentication — Mobile
- Zero-trust remote access: keys pinned at pairing, hole punching or relay, Tor — Client and networking
- Signed, reproducible builds with multi-signer updates and A/B rollback — Updates
- Tor for web search — Settings, Client and networking

## Boot and hardware
- [x] Boot menu: Server / Local, Terminal, Test - SSH Enabled (chat UI + SSH); Secure Client deferred until available
- [x] NVIDIA GPU support (CUDA)
- [x] Keyboard input in kiosk (cage + Chromium)
- [x] Boot vs Local KMS split: boot nvidia-drm modeset=0 (HDMI/console survives); runtime NVIDIA KMS for Local cage/browser
- [x] Real-HW kiosk input: WLR_BACKENDS=drm,libinput; never WLR_LIBINPUT_NO_DEVICES=1 on real hardware (QEMU proofs only)
- [ ] P0 Keyboard-only navigation across the whole UI
  - Note: chat autofocus + NumLock best-effort
- [ ] P1 Distinct failsafe/survival Local path vs full Local browser product UI
- [x] P1 AMD/Intel Vulkan path in v0.3.1 ISO (`llama-server-vulkan` + Mesa; HW confirm pending)
- [ ] P1 Intel Arc polish / SYCL (optional later; Vulkan first)
- [x] P1 CPU-only fallback (v0.3: CPU llama binary + `-ngl 0`, RAM fits check; HW OK on Asus no-NVIDIA)
- [ ] P1 Auto-detect which GPU the monitor is on; pick DRM device automatically
- [ ] P2 Multi-GPU model splitting
- [ ] P2 GPU power/thermal limits (laptops)
- [ ] P1 First-boot hardware report ("your GPU can run X, Y, Z")

## Models
- [x] Small model built into the stick
- [x] Download models from menu to data partition
- [x] P0 Delete models from data partition (v0.3; baked-in models protected)
- [x] P0 Accurate loaded-model identity in UI/status (show what's actually loaded)
- [x] P0 Model load progress UX — clear Loading model / progress so Term/LAN 503 isn't mistaken for broken pairing. v0.4.2: the status poll does not paint Loading until the browser is paired, and the meter starts at 1% instead of jumping to a fake 30%
- [x] P0 Signed model catalog, pinned SHA-256, re-checked at load (v0.3: fatal sha256 on download)
- [x] Slim ISO: bake **3B Q4 only** (~2 GB). **Qwen2.5-7B Q5_K_M** is download-only — shipped v0.3.9 (ISS-020)
- [x] Hugging Face search, one-at-a-time download queue (stop / start / delete, resume), hash check, and VRAM fit labels — v0.3.9
- [ ] **Next** Same filters (Verified / known-hash, Fits in VRAM, Untrusted, quant, licence, abliterated) on **installed models** when choosing what to load into memory — ISS-021
- [ ] **Next** Wire Advanced controls that are on screen but not applied to the running model (sampling, KV cache type, backend). Context size is the part that already moves — ISS-021
- [ ] P1 VRAM-based model suggestions
- [ ] P1 Vision models (restore image input; mmproj hash-pinned)
- [ ] P1 Download unsupported models with explicit warning
  - TODO: decide where the approved/pinned list lives (`catalog.toml` today), how it updates, and how non-list downloads warn + verify (see MODELS.md)
- [ ] P2 Optional large MoE recipe (Strata-style) for high-RAM machines

## Settings (persist on writable partition)
- [ ] P0 Last boot mode is default on menu timeout (GRUB grubenv / savedefault)
- [ ] P0 Menu timeout length
- [ ] P0 Auto-load last model
- [ ] P1 Web search on/off
- [ ] P1 Tor: off / web only / everything
- [ ] P1 Vault on/off; wipe-after-N-failed-tries (configurable or off)
- [ ] P1 Manual display/GPU override
- [x] P1 Settings menu (split from Models) — Network/WiFi, claim USB; stubs for context size / SSD vault / setup AP (v0.3.1)
- [ ] P1 Settings page + reset to defaults (persist all prefs)
- [ ] **Next** Advanced settings panel (per-model inference params) — ISS-021
  - On screen today: context size, presets, KV cache type, temperature, top-p, top-k, repeat penalty, max reply tokens. Presets only move the context slider. Sampling and KV are not sent to llama. The backend segment is disabled (“auto-selected”)
  - Defaults from per-model presets in the signed catalog (template via --jinja, sampling, auto-sized context from free VRAM); see Models → Signed model catalog
  - Still to expose once the greyed knobs work: MoE expert offload, system prompt, thinking toggle
  - Changes save per model in settings; reset-to-preset option
  - UI shows active context size and warns near the limit
- Rule: ordinary UI prefs are not a secret store. Portable secrets (API keys, passwords) and per-computer SSD vault locations live in the encrypted USB settings partition, opened with the same vault passcode. Chats stay in the SSD vault. Voice weights stay in `/opt/stickllm/speech`

## Vault and security
- [x] Ephemeral sessions (reboot clears pair + session)
- [x] P1 Header **Mode** dropdown: Ephemeral (default, no SSD vault writes) | Vault (conscious opt-in)
- [x] P1 Encrypted vault on host SSD — **file blob only** in a user-chosen mounted folder (`feature/encrypted-ssd-vault` / **v0.3.6**); Find/Open existing after reflash; on a current stick, open an existing vault with [Opening an existing vault](docs/VAULT.md#opening-an-existing-vault); never partition/format; fail-closed on BitLocker/unknown/RAID
- [x] P1 Unlock = passcode (+ optional key file on stick DATA)
- [x] P1 USB settings partition, about 256 MB, on the boot stick beside the live image (not a file inside the ISO). In the **v0.4.2** image, first boot reserves it raw; `stickllm-usb-settings` encrypts it with the same LUKS passcode, stick keyfile, and recovery digest as the SSD vault when that vault is unlocked. No second password. Holds per-computer vault locations and portable secrets (the Hugging Face token is stored here once the partition is unlocked). Voice weights stay in `/opt/stickllm/speech`. Chats stay in the SSD vault. A stick whose `STICKLLM-DATA` already fills the disk is not shrunk. Open an existing SSD vault with [Opening an existing vault](docs/VAULT.md#opening-an-existing-vault)
- [x] P1 One-time 12-word recovery phrase shown once at setup
- [x] P1 Failed-attempt counter; wipe-after-N destroys **blob** LUKS header only (default **off**)
- [ ] P1 Panic / duress PIN: opens decoy empty vault, silently destroys real key (server-side)
- [ ] P2 Kiosk/client-stick hold-combo (e.g. hold Ctrl+Alt+W 2s) = quick lock, no wipe
- [x] P1 Browser clients: lock button + Ctrl+Shift+L (auto-lock on disconnect later)
- [ ] P1 Lock vault on stick removal / shutdown
- [ ] P1 Locked-down kiosk browser (RAM profile, strict CSP, localhost only)
- [ ] P2 Secure Boot with own signing key; kernel verifies squashfs hash
- [ ] P2 Boot fingerprint shown on screen; verified by paired client
- [ ] P1 Reproducible, signed builds
- Threat model notes: attempt counters don't stop offline attacks on a copied vault; a stick out of your hands should be reflashed (evil maid)

## Chats and documents
- [x] Chat UI
- [x] P1 Multiple saved chats (titles, search, delete) inside vault — Vault mode only
- [ ] P2 Documents chat / RAG (files + index in vault)
- [ ] P2 Image input (upload, paste, phone camera)

## Client and networking
- [x] P0 WiFi setup (SSID + password) — Settings → Network (when LAN already up); NM profile on STICKLLM-DATA (v0.3; Local WiFi HW OK)
  - Ethernet DHCP still default; web WiFi form works on Local / Server / Term browsers after uplink exists
- [x] P0 Console WiFi bootstrap (no browser) — `stickllm-wifi-setup` on Term/tty2 (scan + password); same `stickllm-wifi-apply` profile (v0.3.1)
  - Server with no Ethernet: Ctrl+Alt+F2 → `user` / `stickllm` → `stickllm-wifi-setup`; or Local-first WiFi then reboot Server; or one-time Ethernet
  - Setup AP for first-time config: deferred (stub in Settings only)
- [ ] P1 True air-gap / NINO (“nothing in, nothing out”) OS network lockdown — ISS-023 (**parked**)
  - Today: UI **Web** pill gates chat live lookup only; Settings **Offline mode** is Coming soon / not wired (does not firewall the OS)
  - Local/Server same machine: disable-network button (kill NIC / block all ingress+egress)
  - Remote client stick: allow only the secure tunnel to the paired server; block all other traffic
- [ ] P0 Client USB stick (boots straight to browser)
- [ ] P0 Pairing via QR / on-screen code with pinned TLS cert
- [ ] P1 Trusted HTTPS with no browser warnings (Plex-style; StickLLM web clients only)
  - Each server gets a subdomain (e.g. a1b2c3.stickllm.net) pointing at its LAN IP
  - Let's Encrypt cert via DNS-01 through the rendezvous service
  - QR code opens that https URL directly
  - Fallback for routers that block private-IP DNS answers: in-page encryption using the key from the QR code
  - Concrete design for warning-free browser access; pairs with P0 QR/TLS pairing and P2 WAN rendezvous
- [ ] P2 WAN: rendezvous + hole punching, relay fallback
- [ ] P2 Self-hostable rendezvous
- [ ] P2 Tor onion service for remote access (no open ports)
- [ ] P2 Model downloads over Tor (hash-verified)
- [x] ~~P2 OpenAI-compatible API for LAN apps~~ — **removed in v0.3** (ISS-004): StickLLM UI only (`/api/chat` + `X-StickLLM-Client`); `/v1/chat/completions` returns 410 for third parties.
- [ ] P2 Multi-user server, separate vault per client

## Mobile
- [ ] P1 PWA client (iOS, Android, GrapheneOS)
- [ ] P1 QR pairing via phone camera
- [ ] P1 Chats in memory or vault only, never on phone
- [ ] P2 Native apps: iOS, Android (Play, F-Droid / direct APK, no Google services)

## Updates
- [ ] P1 A/B system slots (squashfs) with automatic rollback via GRUB
- [ ] P1 Signed updates; never touch data partition or models
- [ ] P1 Model updates via signed catalog

## Companion apps (planned)
- [x] P2 Starter add-ons installable from the Apps page — **0.5.0** (not hardware-tested yet): Radicale 3.9.0, Vikunja 2.7.1, Actual Budget 26.10.0, Trilium v0.106.1, Node-RED 5.0.9. **0.5.4:** Radicale, Vikunja and Actual removed; Tasks.md 3.3.0, Paisa v0.7.8 and ComfyUI (GPU optional) added; Trilium opens with no login after an automatic first-start setup. Pulled by digest on Install, data in the vault, no internet or LAN for the containers, no Docker logs, read-only root, opened in a new tab through the gateway. Node-RED flows can run arbitrary code. See [docs/APPS.md](docs/APPS.md#installable-from-the-apps-page-050)
- [x] P1 Agent Zero plugins: banned unless allowlisted — **0.5.0**; removed altogether — **0.5.4** (empty allowlist enforced by the build, installer plugins deleted in the container, kiosk console included). The two 0.5.0 plugins (clock_24h, chat_status_marklet) are gone; see [docs/PLUGIN-REVIEWS.md](docs/PLUGIN-REVIEWS.md)
- [ ] P2 Rest of the companion catalog (Immich, Paperless-ngx, …; ComfyUI ships in 0.5.4) — [docs/APPS.md](docs/APPS.md) (ISS-022); not shipping yet
- [x] P2 Voice input + read-aloud — in the **v0.4.2** ISO. Voice on/off keeps whisper.cpp tiny.en and KittenTTS mini 0.8 resident (Bella by default), including `whisper-server`. Replies stream to speech; Stop speaking cuts that audio. While Voice is on, the reply budget is 80 tokens, a short spoken-style instruction is sent without appearing in the thread, and thinking text is not shown or spoken. After real speech, 1 second of silence sends the line. Weights are image-build pins (`overlay/usr/local/lib/stickllm-speech.pin`), not downloaded at runtime, and not stored in the vault. Wake word is still later.

## UI and extras
- [ ] P1 Status/health page (GPU temp, VRAM, tok/s, loaded model); doubles as Server/Term screen
- [ ] P2 Localisation
- [ ] P2 Offline help docs on stick
