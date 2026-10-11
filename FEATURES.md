# StickLLM Features

Legend: [x] working today, [ ] planned. Priority: P0 = next, P1 = soon, P2 = later.

## Boot and hardware
- [x] Boot menu: Local, Server, Term
- [x] NVIDIA GPU support (CUDA)
- [x] Keyboard input in kiosk (cage + Chromium)
- [x] Boot vs Local KMS split: boot nvidia-drm modeset=0 (HDMI/console survives); runtime NVIDIA KMS for Local cage/browser
- [x] Real-HW kiosk input: WLR_BACKENDS=drm,libinput; never WLR_LIBINPUT_NO_DEVICES=1 on real hardware (QEMU proofs only)
- [ ] P0 Keyboard-only navigation across the whole UI
  - Note: chat autofocus + NumLock best-effort
- [ ] P1 Distinct failsafe/survival Local path vs full Local browser product UI
- [ ] P1 AMD GPUs (ROCm or Vulkan)
- [ ] P1 Intel Arc / iGPU (Vulkan or SYCL)
- [ ] P1 CPU-only fallback
- [ ] P1 Auto-detect which GPU the monitor is on; pick DRM device automatically
- [ ] P2 Multi-GPU model splitting
- [ ] P2 GPU power/thermal limits (laptops)
- [ ] P1 First-boot hardware report ("your GPU can run X, Y, Z")

## Models
- [x] Small model built into the stick
- [x] Download models from menu to data partition
- [ ] P0 Delete models from data partition
- [ ] P0 Accurate loaded-model identity in UI/status (show what's actually loaded)
- [ ] P0 Model load progress UX — clear Loading model / progress so Term/LAN 503 isn't mistaken for broken pairing
- [ ] P0 Signed model catalog, pinned SHA-256, re-checked at load
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
- [ ] P1 Settings page + reset to defaults
- Rule: settings hold nothing revealing; anything sensitive lives in the vault

## Vault and security
- [x] Ephemeral sessions (reboot clears pair + session)
- [ ] P1 Encrypted vault on host SSD (LUKS2, Argon2id), only carved from free space, never auto-format
- [ ] P1 Unlock = key file on stick + short PIN
- [ ] P1 One-time 12-word recovery phrase for a lost stick
- [ ] P1 Failed-attempt counter that survives reboot; wipe destroys LUKS header/key file
- [ ] P1 Panic / duress PIN: opens decoy empty vault, silently destroys real key (server-side)
- [ ] P2 Kiosk/client-stick hold-combo (e.g. hold Ctrl+Alt+W 2s) = quick lock, no wipe
- [ ] P1 Browser clients: lock button + Ctrl+Shift+L; auto-lock on disconnect/timeout
- [ ] P1 Lock vault on stick removal / shutdown
- [ ] P1 Locked-down kiosk browser (RAM profile, strict CSP, localhost only)
- [ ] P2 Secure Boot with own signing key; kernel verifies squashfs hash
- [ ] P2 Boot fingerprint shown on screen; verified by paired client
- [ ] P1 Reproducible, signed builds
- Threat model notes: attempt counters don't stop offline attacks on a copied vault; a stick out of your hands should be reflashed (evil maid)

## Chats and documents
- [x] Chat UI
- [ ] P1 Multiple saved chats (titles, search, delete) inside vault
- [ ] P2 Documents chat / RAG (files + index in vault)
- [ ] P2 Image input (upload, paste, phone camera)

## Client and networking
- [ ] P0 WiFi setup (SSID + password) — credentials UI for StickLLM, especially Local Web / outbound internet
  - Today: Ethernet DHCP only; no WiFi credentials UI
- [ ] P0 Client USB stick (boots straight to browser)
- [ ] P0 Pairing via QR / on-screen code with pinned TLS cert
- [ ] P1 Plain browser access without cert warnings (local CA via pairing, or in-page encryption)
- [ ] P2 WAN: rendezvous + hole punching, relay fallback
- [ ] P2 Self-hostable rendezvous
- [ ] P2 Tor onion service for remote access (no open ports)
- [ ] P2 Model downloads over Tor (hash-verified)
- [~] ~~P2 OpenAI-compatible API for LAN apps (token from pairing)~~ — **removed next version** (ISS-004): do not ship an external/OpenAI LAN API; privacy path = StickLLM-controlled UI only (Local + Server/Term web). Pairing may stay for the StickLLM web client if needed.
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
