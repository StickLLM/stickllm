# StickLLM Features

Legend: [x] working today, [ ] planned. Priority: P0 = next, P1 = soon, P2 = later.

## Boot and hardware
- [x] Boot menu: Server / Local, Secure Client, Terminal, Test (chat UI + SSH)
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
- [x] P0 Model load progress UX — clear Loading model / progress so Term/LAN 503 isn't mistaken for broken pairing
- [x] P0 Signed model catalog, pinned SHA-256, re-checked at load (v0.3: fatal sha256 on download)
- [ ] P1 VRAM-based model suggestions
- [ ] P1 Vision models (restore image input; mmproj hash-pinned)
- [ ] P1 Download unsupported models with explicit warning
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
- [ ] P1 Advanced settings panel (per-model inference params)
  - Defaults from per-model presets in the signed catalog (template via --jinja, sampling, auto-sized context from free VRAM); see Models → Signed model catalog
  - Exposes: temperature, top_p, top_k, context size, KV cache type, MoE expert offload, system prompt, thinking toggle
  - Changes save per model in settings; reset-to-preset option
  - UI shows active context size and warns near the limit
- Rule: settings hold nothing revealing; anything sensitive lives in the vault

## Vault and security
- [x] Ephemeral sessions (reboot clears pair + session)
- [x] P1 Header **Mode** dropdown: Ephemeral (default, no SSD vault writes) | Vault (conscious opt-in)
- [x] P1 Encrypted vault on host SSD — **file blob only** in a user-chosen mounted folder (`feature/encrypted-ssd-vault` / v0.3.3); never partition/format; fail-closed on BitLocker/unknown/RAID; SSH-test first
- [x] P1 Unlock = passcode (+ optional key file on stick DATA)
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
- [ ] P2 Voice input + TTS

## Updates
- [ ] P1 A/B system slots (squashfs) with automatic rollback via GRUB
- [ ] P1 Signed updates; never touch data partition or models
- [ ] P1 Model updates via signed catalog

## UI and extras
- [ ] P1 Status/health page (GPU temp, VRAM, tok/s, loaded model); doubles as Server/Term screen
- [ ] P2 Localisation
- [ ] P2 Offline help docs on stick
