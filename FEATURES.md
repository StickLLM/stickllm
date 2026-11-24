# StickLLM Features

Legend: [x] working today, [ ] planned. Priority: P0 = next, P1 = soon, P2 = later.

Ship through **v0.8.8** (`StickLLM-v0.8.8.iso`, `c5aa2305…`). Next bake: [docs/NEXT-0.8.9.md](docs/NEXT-0.8.9.md) — that file is the source of truth for must-bake, not this checklist and not chat. Security architecture is parked until the working product is settled. Do not start NINO, the client-stick lockdown, zero-trust remote access, or signed multi-signer updates before then.

**Next (P0 / v0.8.9):** vault lock = ephemeral only so StickLLM + Agent Zero keep running without unlock (ISS-076); dual-USB settings open when DATA is on a second stick (ISS-074); corrupt A0 docker graph detect/reseed (ISS-075); optional Advanced VRAM-ceiling warn for NInfer high context (TU3 / follow-on ISS-072). Still open later: same load filters on installed models and Advanced sampling knobs that are greyed (ISS-021); AMD / Intel polish.

## Ideas

Working today:

- Boot menu: Local / Server (GPU chat or share on the LAN), Terminal, Test (SSH enabled for maintainers)
- Debian 13 base; NVIDIA CUDA acceleration, with Vulkan and CPU fallback
- Built-in model, plus Hugging Face download for GGUF and NInfer `.ninfer` (queue Stop / Resume / Delete, hash check, VRAM fit labels)
- Experimental **NInfer** / Strata Set default on `:8080` (Confirm; switch back to llama.cpp); NInfer HF token; Context slider + Load guard
- Download to free RAM + async USB persist when RAM allows; USB→RAM stage before Load; RAM spike guard
- Kiosk chat UI (desktop and phone browser), pair on the LAN with a one-time code
- **StickLink** Method C phone join / Always-On peer (in the ISO; Worker/cloud and StickDroid APK are separate)
- **Agent Zero** seeded in Docker; desk + StickLink open `/agent-zero/`; VL / phone image attach when a vision model is loaded
- Ephemeral by default: reboot clears the session. Optional encrypted vault for durable chats/secrets (tree still hard-gates A0 on vault unlock — **planned v0.8.9**, ISS-076)
- About 256 MB USB settings partition: raw on first boot, formatted with the vault passcode on unlock (HF token lives here when unlocked)
- Web mode: Internet / Tor / No internet (taskbar Web + Settings → Network)
- Voice on/off: resident Whisper and Kitten, streaming speech, stop button, one-second silence sends after real speech
- Mount host drives or claim free space on the StickLLM stick
- Shipping ISOs as `StickLLM-vX.Y.Z.iso` (flash with Rufus DD Image, or build from source)

Still to build, in order. Each line points at the checklist section that owns it:

1. **Next (v0.8.9).** Vault lock = ephemeral (not an A0 hard gate); dual-USB settings; A0 graph repair — Vault and security, Companion apps (ISS-076 / 074 / 075; NEXT-0.8.9)
2. Finish model filters on installed models, and wire the greyed Advanced section — Models, Settings (ISS-021)
3. Stronger AMD / Intel GPU paths and broader hardware coverage — Boot and hardware
4. **Multi-device pairing (up to 8)** on one stick / shared vault — phone, LAN browser, AIKVM, speaker/mic, etc. (LAN + StickLink). Today = one paired device at a time. Admin / per-user vaults later — Client and networking (ISS-077)
5. **Phone Chat / Work / A0** — restore StickLLM Chat for simple; Work = simplified A0; A0 = full agent (ISS-078). **Web client** https://stickllm.com/app/ as APK alternative (ISS-079)
6. Rest of the vault story: stick key + PIN. The 12-word recovery phrase already exists. Panic / duress PIN stays parked — Vault and security
7. Saved settings and per-model presets (saved chats already exist) — Settings
8. Document RAG (vision / phone image attach already ships for VL) — Chats and documents
9. Agent voice (wake word) — chat Voice on/off, streaming speech, and read-aloud already ship; see Companion apps
10. More apps from the catalog — [docs/APPS.md](docs/APPS.md)

Parked with security (do not build yet):

- Dedicated client stick paired with a server stick — Client and networking
- Mobile apps (iOS, GrapheneOS store builds) with QR pairing — Mobile (StickDroid / StickLink phone path is separate from this parked native-apps line)
- Zero-trust remote access redesign beyond StickLink: keys pinned at pairing, hole punching or relay, Tor — Client and networking
- Signed, reproducible builds with multi-signer updates and A/B rollback — Updates
- Tor for model downloads / “everything” mode — Settings, Client and networking (stick **Web** Tor mode already ships)

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
- [ ] **P2 Experimental — Project Maya + Inkling 2 Mini** — [alesha-pro/maya-inkling-mini](https://github.com/alesha-pro/maya-inkling-mini) (3090 guide) / [mw00/project-maya](https://github.com/mw00/project-maya) `maya-ik2`: ~125 tok/s plain, **~200 tok/s** code/edits with DSpark. Not [sfnx](https://github.com/johnfink8/sfnx). Same Experimental Cancel/Continue + Set default as NInfer/Strata. Track: **ISS-080**
- [ ] P2 GPU power/thermal limits (laptops)
- [ ] P1 First-boot hardware report ("your GPU can run X, Y, Z")

## Models
- [x] Small model built into the stick
- [x] Download models from menu to data partition
- [x] P0 Delete models from data partition (v0.3; baked-in models protected)
- [x] P0 Accurate loaded-model identity in UI/status (show what's actually loaded)
- [x] P0 Model load progress UX — clear Loading model / progress so Term/LAN 503 isn't mistaken for broken pairing. v0.4.2: the status poll does not paint Loading until the browser is paired, and the meter starts at 1% instead of jumping to a fake 30%
- [x] P0 Signed model catalog, pinned SHA-256, re-checked at load (v0.3: fatal sha256 on download)
- [x] Baked default GGUF: **Qwen2.5-7B Instruct Q4_K_M** (current ship v0.8.8). **Q5_K_M** remains download-only. Earlier slim-ISO “3B only” experiment is historical — see [docs/MODELS.md](docs/MODELS.md)
- [x] Hugging Face search, one-at-a-time download queue (stop / start / delete, resume), hash check, and VRAM fit labels — v0.3.9
- [x] **v0.8.7–v0.8.8** NInfer Models path: HF search for `.ninfer`, Load / sticky Load, queue Stop / Resume / Delete, engine-scoped search (no GGUF as NInfer), false “loading / Downloading Qwen2.5” fixed (ISS-044…046, 052, 059, 060, 065, 068, 069)
- [x] **v0.8.7–v0.8.8** USB→RAM stage before Load; download to free RAM + async USB persist; RAM spike guard; Models “Saving to USB” while durable copy finishes (ISS-053, 070, 071, 073)
- [x] **v0.8.8** NInfer HF token export for catalog / gated pulls; Test whoami (ISS-066)
- [x] **v0.8.8** NInfer Context slider + Load guard (`--max-context` / `--kv-capacity`, refuse when headroom unsafe; prefer existing tmpfs stage) (ISS-072)
- [ ] **Next** Same filters (Verified / known-hash, Fits in VRAM, Untrusted, quant, licence, abliterated) on **installed models** when choosing what to load into memory — ISS-021
- [ ] **Next** Wire Advanced controls that are on screen but not applied to the running model (sampling, KV cache type, backend). Context size already moves for llama and NInfer — ISS-021 / ISS-058
- [ ] P1 VRAM-based model suggestions
- [x] P1 Vision models (VL catalog + mmproj; phone / chat image attach when VL loaded — v0.8.3+)
  - Still open: broader vision catalog polish; mmproj hash-pin policy continues as today
- [ ] P1 Download unsupported models with explicit warning
  - TODO: decide where the approved/pinned list lives (`catalog.toml` today), how it updates, and how non-list downloads warn + verify (see MODELS.md)
- [ ] P2 Optional large MoE recipe (Strata-style) for high-RAM machines
- [ ] P2 Experimental Project Maya `maya-ik2` + Inkling 2 Mini on 3090 (~125 / ~200 tok/s) — ISS-080; [docs/DEBIAN13-EXPERIMENTAL.md](docs/DEBIAN13-EXPERIMENTAL.md)
- [x] P1 **v0.8.0** Debian 13 fresh image + Experimental tab scaffolding (Strata / NInfer-all offers; CMP 170HX + RTX 3090 unlock UI stubs) — [docs/DEBIAN13-EXPERIMENTAL.md](docs/DEBIAN13-EXPERIMENTAL.md); artifact `StickLLM-v0.8.0.iso`; no auto-install; no NVIDIA blobs in git
- [x] P1 **v0.8.2** Experimental Set default (NInfer/Strata on :8080); VL-3B dropped → VL-7B (≥12 GB); prior 0.8.1 hotfixes — artifact `StickLLM-v0.8.2.iso`
- [x] P1 **v0.8.1** Experimental engines + unlocks wired (Cancel/Continue; no master toggle); vault delete / novault probe; llama b12617 + mmproj; MoE/32K refuse-if-unfit; HF typo search; download→Installed refresh; firmware-mediatek; A0 MiniLM skip — artifact `StickLLM-v0.8.1.iso`

## Settings (persist on writable partition)
- [ ] P0 Last boot mode is default on menu timeout (GRUB grubenv / savedefault)
- [ ] P0 Menu timeout length
- [ ] P0 Auto-load last model
- [x] P1 Web mode: Internet / Tor / No internet (taskbar **Web** + Settings → Network; persists; Tor on demand) — see [docs/WEB-MODE.md](docs/WEB-MODE.md)
- [ ] P1 Tor: “everything” / model downloads over Tor (Web Tor mode already ships)
- [ ] P1 Vault on/off; wipe-after-N-failed-tries (configurable or off)
- [ ] P1 Manual display/GPU override
- [x] P1 Settings menu (split from Models) — Network/WiFi, claim USB; stubs for context size / SSD vault / setup AP (v0.3.1)
- [ ] P1 Settings page + reset to defaults (persist all prefs)
- [ ] **Next** Advanced settings panel (per-model inference params) — ISS-021
  - On screen today: context size, presets, KV cache type, temperature, top-p, top-k, repeat penalty, max reply tokens. Context moves for llama and NInfer. Sampling and KV are not fully applied to llama; KV greyed under NInfer. The backend segment is disabled (“auto-selected”)
  - Defaults from per-model presets in the signed catalog (template via --jinja, sampling, auto-sized context from free VRAM); see Models → Signed model catalog
  - Still to expose once the greyed knobs work: MoE expert offload, system prompt, thinking toggle
  - Changes save per model in settings; reset-to-preset option
  - UI shows active context size and warns near the limit
  - **Planned v0.8.9:** optional Advanced warn near GPU VRAM ceiling for NInfer high ctx (TU3)
- Rule: ordinary UI prefs are not a secret store. Portable secrets (API keys, passwords) and per-computer SSD vault locations live in the encrypted USB settings partition, opened with the same vault passcode. Chats stay in the SSD vault. Voice weights stay in `/opt/stickllm/speech`

## Vault and security
- [x] Ephemeral sessions (reboot clears pair + session)
- [x] P1 Header **Mode** dropdown: Ephemeral (default, no SSD vault writes) | Vault (conscious opt-in)
- [x] P1 Encrypted vault on host SSD — **file blob only** in a user-chosen mounted folder (`feature/encrypted-ssd-vault` / **v0.3.6**); Find/Open existing after reflash; on a current stick, open an existing vault with [Opening an existing vault](docs/VAULT.md#opening-an-existing-vault); never partition/format; fail-closed on BitLocker/unknown/RAID
- [x] P1 Unlock = passcode (+ optional key file on stick DATA)
- [x] P1 USB settings partition, about 256 MB, on the boot stick beside the live image (not a file inside the ISO). In the **v0.4.2** image, first boot reserves it raw; `stickllm-usb-settings` encrypts it with the same LUKS passcode, stick keyfile, and recovery digest as the SSD vault when that vault is unlocked. No second password. Holds per-computer vault locations and portable secrets (the Hugging Face token is stored here once the partition is unlocked). Voice weights stay in `/opt/stickllm/speech`. Chats stay in the SSD vault. A stick whose `STICKLLM-DATA` already fills the disk is not shrunk. Open an existing SSD vault with [Opening an existing vault](docs/VAULT.md#opening-an-existing-vault)
- [x] P1 One-time 12-word recovery phrase shown once at setup
- [x] P1 Failed-attempt counter; wipe-after-N destroys **blob** LUKS header only (default **off**)
- [x] P1 Delete vault and start fresh in setup (corrupt / wrong password / Forgot password?) — **v0.8.5** (ISS-037)
- [ ] **P0 / planned v0.8.9** Vault lock = ephemeral only: StickLLM + Agent Zero keep running without unlock (tmpfs chats; no durable secrets). Unlock enables vault save / HF in settings / durable A0. Tree still hard-gates dockerd/A0 on vault mount today — ISS-076
- [ ] **P0 / planned v0.8.9** Dual-USB: open `STICKLLM-SETTINGS` on the DATA disk when boot stick has no settings — ISS-074
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
- [x] P1 Image input when a VL model is loaded (upload / phone attach; StickLink shrink ≤1280 JPEG — v0.8.3 / ISS-063)
  - Paste / camera UX polish still open

## Client and networking
- [x] P0 WiFi setup (SSID + password) — Settings → Network (when LAN already up); NM profile on STICKLLM-DATA (v0.3; Local WiFi HW OK)
  - Ethernet DHCP still default; web WiFi form works on Local / Server / Term browsers after uplink exists
- [x] P0 Console WiFi bootstrap (no browser) — `stickllm-wifi-setup` on Term/tty2 (scan + password); same `stickllm-wifi-apply` profile (v0.3.1)
  - Server with no Ethernet: Ctrl+Alt+F2 → `user` / `stickllm` → `stickllm-wifi-setup`; or Local-first WiFi then reboot Server; or one-time Ethernet
  - Setup AP for first-time config: deferred (stub in Settings only)
- [x] P1 Local timezone on first internet (geolocate public IP; NTP after Wi‑Fi) — **v0.8.7–v0.8.8** (ISS-047, 067)
- [x] P0 StickLink Method C phone join / Always-On peer in the shipping ISO (QR on Devices; keepalive under load; A0 sync rewrite; large photo mux; work-dir downloads — through **v0.8.8**). StickLink Worker / signalling remains closed source. StickDroid APK is not in the ISO
- [ ] P1 True air-gap / NINO (“nothing in, nothing out”) OS network lockdown — ISS-023 (**parked**)
  - Today: UI **Web** pill gates stick browser uplink (Internet / Tor / No internet); Settings **Offline mode** Coming soon is not the same as NINO
  - Local/Server same machine: disable-network button (kill NIC / block all ingress+egress)
  - Remote client stick: allow only the secure tunnel to the paired server; block all other traffic
- [ ] P0 Client USB stick (boots straight to browser)
- [ ] P0 Pairing via QR / on-screen code with pinned TLS cert (LAN pair code ships; StickLink QR is the phone path)
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
- [ ] **P1 Multi-device pairing (up to 8)** — several clients paired to **one stick** at once (phone, LAN/browser, AIKVM, speaker/mic, …) over **LAN pair and/or StickLink**. Today effectively **one** active paired device. **Phase 1:** concurrent sessions sharing the stick’s single vault / session mode (no admin/roles yet). **Phase 2 (later):** admin vs other users, shared vs separate vaults — open design. Track: **ISS-077**. Supersedes the old one-liner “multi-user server, separate vault per client” as the first milestone.
- [ ] P2 Multi-user / roles + optional separate vault per user (after Phase 1 multi-device) — ISS-077 phase 2

## Mobile
- [ ] **P1 Chat / Work / A0 modes** — **Chat** = StickLLM `/api/chat` (old `#app` UI; simple + optional Web). **Work** = today’s Android “Chat” renamed (A0 with complexity hidden). **A0** = full Agent Zero. ChatGPT-style: simple vs multi-step. **Chat → A0 handoff required** (explicit Work/A0 switch or “send to agent”; stick already has Agent Zero toggle → `/api/agent/ask` + inline steps). Soft suggest OK; silent auto-escalate later. Stick Chat code still present; desk WinBox mount retired. Track: **ISS-078**
- [ ] **P1 Phone web client** — https://stickllm.com/app/ (QR scan → connect → phone site). Goal: replace StickDroid APK when connection/timeouts are solid. Lab WIP; APK remains until then. Track: **ISS-079**
- [ ] P1 PWA / installable web client (iOS, Android, GrapheneOS) — overlaps ISS-079
- [ ] P1 QR pairing via phone camera (StickLink QR path ships on the stick; StickDroid / stickllm.com/app)
- [ ] P1 Chats in memory or vault only, never on phone
- [ ] P2 Native apps: iOS, Android (Play, F-Droid / direct APK, no Google services) — fallback if web client is not enough

## Updates
- [ ] P1 A/B system slots (squashfs) with automatic rollback via GRUB
- [ ] P1 Signed updates; never touch data partition or models
- [ ] P1 Model updates via signed catalog

## Companion apps (planned)
- [x] P2 Starter add-ons installable from the Apps page — **0.5.0** (not hardware-tested yet): Radicale 3.9.0, Vikunja 2.7.1, Actual Budget 26.10.0, Trilium v0.106.1, Node-RED 5.0.9. **0.5.4:** Radicale, Vikunja and Actual removed; Tasks.md 3.3.0, Paisa v0.7.8 and ComfyUI (GPU optional) added; Trilium opens with no login after an automatic first-start setup. Pulled by digest on Install, data in the vault, no internet or LAN for the containers, no Docker logs, read-only root, opened in a new tab through the gateway. Node-RED flows can run arbitrary code. See [docs/APPS.md](docs/APPS.md#installable-from-the-apps-page-ships-in-v088)
- [x] P1 Agent Zero — ships seeded (Docker on DATA); desk / LAN / StickLink open `/agent-zero/`; offline first-start + exec bits — **v0.8.5** (ISS-038). **Planned v0.8.9:** run when vault locked (ISS-076); dual-USB settings (ISS-074); corrupt graph reseed (ISS-075)
- [x] P1 Agent Zero plugins: banned unless allowlisted — **0.5.0**; removed altogether — **0.5.4** (empty allowlist enforced by the build, installer plugins deleted in the container, kiosk console included). The two 0.5.0 plugins (clock_24h, chat_status_marklet) are gone; see [docs/PLUGIN-REVIEWS.md](docs/PLUGIN-REVIEWS.md)
- [ ] P2 Rest of the companion catalog (Immich, Paperless-ngx, …; ComfyUI ships in 0.5.4) — [docs/APPS.md](docs/APPS.md) (ISS-022); not shipping yet
- [x] P2 Voice input + read-aloud — in the **v0.4.2** ISO. Voice on/off keeps whisper.cpp tiny.en and KittenTTS mini 0.8 resident (Bella by default), including `whisper-server`. Replies stream to speech; Stop speaking cuts that audio. While Voice is on, the reply budget is 80 tokens, a short spoken-style instruction is sent without appearing in the thread, and thinking text is not shown or spoken. After real speech, 1 second of silence sends the line. Weights are image-build pins (`overlay/usr/local/lib/stickllm-speech.pin`), not downloaded at runtime, and not stored in the vault. Wake word is still later.

## UI and extras
- [ ] P1 Status/health page (GPU temp, VRAM, tok/s, loaded model); doubles as Server/Term screen
- [ ] P2 Localisation
- [ ] P2 Offline help docs on stick
