## 0.7.2 - TEST (lab-assisted Method C preview; shipping tag pending HW)
- **Devices & Pairing StickLink QR.** Kiosk shows the StickLink phone join QR
  (cellular → Agent Zero), not the LAN address. Gateway
  `GET /api/pair/sticklink-join` + remint; `stickllm-sticklink-join-publish` writes
  `/run/stickllm/sticklink-join.json`.
- **Method C lab-assisted preview.** Rendezvous → WebRTC → Noise → app-mux DC.
  Join peer + trusted-approval lab grants remain on the lab host (not Phase 2).
  Known-good tag: `methodc-lte-accept-20261108.1`.
- **SearXNG.** Prefer Bing/Yahoo/Seznam/Wikipedia when Google/DDG/Brave CAPTCHA
  on shared egress.
- **Known / deferred:** ISS-033 LAN/desktop pairing broken (not fixed);
  ISS-034 lab repeated-Send automation timeout. No shipping tag until HW accept.

## 0.7.1 - StickLink deps bake
- **StickLink host deps.** Bake `python3-cryptography`, `python3-nacl`, and
  `python3-websockets` so `sticklinkd` can start. v0.7.0 shipped the StickLink
  overlay/config but the host Python was missing cryptography (`ModuleNotFoundError`
  on lab stick). Do not overwrite `StickLLM-v0.7.0.iso`.

## 0.6.12 - WIP (tree only — not baked/flashed)
- **Official Agent Zero logo.** Desktop / nav icon uses the Agent Zero A0 mark
  (from agent0ai/agent-zero); Discord approval from Jan Tomášek is filed at
  [docs/legal/AGENT-ZERO-LOGO.md](docs/legal/AGENT-ZERO-LOGO.md).
- **Browser home page.** Opening the desktop Browser lands on a local
  `http://127.0.0.1/browser-home.html` with the StickLLM logo and live Web mode
  (Internet / Tor / No internet) from `/api/web-mode`.
- **Tor no longer traps Wi-Fi / mode switching.** Tor used to set a system-wide
  Chromium SOCKS policy, so StickLLM Settings / Wi-Fi looked dead. Tor mode now
  installs a Chromium **PAC** (LAN/loopback DIRECT, else SOCKS5) because managed
  `ProxyMode=direct` overrode Browser `--proxy-server` and “what’s my IP” showed
  the real address. No-internet allowlist still includes private LAN StickLLM.
  Mode changes do not restart kiosk. `tor_ready` requires check.torproject.org
  `"IsTor": true`. Toggling Tor closes desktop Browser windows. Docs:
  [docs/WEB-MODE.md](docs/WEB-MODE.md).
- **Delete vault in Settings → Storage & Vault.** Pick a known location (SSD / USB
  DATA / …), enter the vault passcode, type **`DELETE_VAULT`**. Strong warning:
  erases your data with no backup. Reuses Lock teardown (stop A0, umount) then
  destroys only that `stickllm-vault.img` (never whole disks). Sibling `models/`,
  DATA models, USB settings LUKS / pairing survive; setup markers clear so
  create/attach can run again. Control: `vault_delete` → `stickllm-vault destroy`.
  Docs: [docs/VAULT.md](docs/VAULT.md).
- **Ephemeral Agent Zero chats stay off the vault.** `a0_chats_dir` / `stickllm-agent`
  previously bind-mounted `<vault>/chats/agent-zero` whenever a store was open,
  even with session mode Ephemeral (gateway StickLLM chat APIs already gated).
  Ephemeral now mounts `/run/stickllm/a0-chats` (tmpfs); Vault mode mounts the
  encrypted store. Mode switch try-restarts A0 to remount; Lock vault still stops
  A0 cleanly. Docs: [docs/CHATS.md](docs/CHATS.md), [docs/VAULT.md](docs/VAULT.md).

## 0.6.11 - 2026-11-07
- **Kiosk mic/camera: no Allow prompt.** Stick Chromium enterprise policy
  `AudioCaptureAllowedUrls` / `VideoCaptureAllowedUrls` (`stickllm-media.json`,
  refreshed at kiosk start for loopback + this stick’s LAN/pair IPs) auto-grants
  capture for StickLLM origins. Remote phone/PC browsers still need HTTPS + a
  normal user Allow. Docs: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).
  `stickllm-hotfix` now installs `etc/chromium/policies/managed/stickllm-*.json`.
- **Web mode (Internet / Tor / No internet) for the stick browser.** Taskbar **Web** (next to Vault) and Settings → Network choose the mode. **Internet** = normal Chromium uplink; **Tor** starts on-demand `tor.service` and points stick Chromium at `socks5://127.0.0.1:9050`; **No internet** URL-blocklists the public web while loopback StickLLM still works. Mode persists under `/var/lib/stickllm/web-mode.json` (and the USB settings partition when mounted); `stickllm-web-mode.service` reapplies at boot.
- **Honest remote-client scope.** Web/Tor/No-internet applies to the **stick kiosk browser** and stick-local Chromium (plus stick-origin web lookup/fetch). Paired LAN browsers keep their own network — the UI says so; StickLLM does not pretend to Tor-proxy a phone or PC browser.
- Package `tor` on the image; Tor is disabled at boot and only started while Web mode is Tor. CLI: `stickllm-web-mode status|set|apply`. Docs: [docs/WEB-MODE.md](docs/WEB-MODE.md).

## 0.6.10 - 2026-11-07
- **Root-cause fix for “Agent Zero shows 127.0.0.1 refused to connect” on first open.** `/api/agent/status` derived `running` from a bare TCP connect to `127.0.0.1:5099`. The container publishes that port through `docker-proxy`, which binds and accepts it the moment the container is created — about **55 s** before Agent Zero itself starts answering. For that whole window the gateway reported `state=running, running=true` while `/agent-zero/` returned 502 and `http://127.0.0.1:5099/` reset the connection, so the UI said “Agent Zero is ready”, embedded a dead endpoint, and Chromium painted the refused-to-connect page until the user reloaded the desktop. `running` now requires a real HTTP reply from A0 (`_agent_http_ready`, short-cached); the `/agent-zero/` proxy uses the same gate and returns a clean 503 “Agent Zero is not running yet” while starting. Measured in QEMU `E:\stickllm-vm\v068`: 52 contradictory samples before, **0 after**; the panel now shows “Agent Zero is starting…” and swaps itself to the live embed.
- **USB settings could deadlock Agent Zero permanently.** `stickllm-usb-settings open` / `open-or-init` assumed the LUKS mapper was closed. After an interrupted unlock the mapping survives with nothing mounted, so every retry died on “Device stickllm-settings already exists” and the agent sat at `settings_missing` with no way back short of a manual `cryptsetup close`. The open paths now adopt a live mapping that already backs the same partition (and drop one that backs a different partition). `open-or-init` also finishes an init where `luksFormat` succeeded but `mkfs` never ran — previously an unrecoverable “bad superblock” on every unlock. Formatting still requires `STICKLLM_SETTINGS_INIT=1`, i.e. the vault already accepted the passcode.
- **A truncated docker reference store no longer bricks Agent Zero for good.** An unclean power-off — the stick pulled, or the host cut mid-write — can leave `image/overlay2/repositories.json` at zero bytes. `dockerd` then failed every single start with `invalid image <digest>, failed to verify` and `Couldn't create reference store repository: EOF`, so A0 never came up again on any later boot and nothing retried it. `ensure-seeded` now restores that file from the read-only seed when it is missing or empty; it is only a small tag→digest index, and layer content is never touched. Previously `image/` was refreshed only when absent entirely, so a *damaged* one was left in place forever.
- **`stickllm-agent.service` restart limits never applied.** `StartLimitIntervalSec` / `StartLimitBurst` were in `[Service]`, where systemd logs `Unknown key … ignoring` and drops them, so `Restart=always` retried a broken dependency indefinitely (observed at 16 consecutive restarts). Moved to `[Unit]`, where they take effect.
- Disposable QEMU harness `E:\stickllm-vm\v068` is reliable again: one-command `up` (boot → HTTP → SSH key → tunnels, ~60 s), `prep` (SSD, vault, USB settings, docker seed), `a0start` / `a0stop` / `a0wait`, `a0` status, `netdiag`. Agent Zero is started through `stickllm-agent.service` instead of a backgrounded `stickllm-agent start`, which systemd killed with the oneshot unit's cgroup — the old reason A0 never left `locked` and CSRF stayed 503 forever.
- Dropped a stray `stickllm-gateway.bak-pre-urlprefix` from `overlay/usr/local/bin/`, which would have shipped inside the ISO.
- Build refuses `VERSION=0.6.9` now that it is a published ship. UI cache bust `v0610`.
- **Test/Terminal SSH password minting restored** (tree): random per-boot password again on READY / F10. The empty-password + `PermitEmptyPasswords` WIP for VM OCR is reverted — not flashed / not baked unless asked.

## 0.6.9 - 2026-11-06
- **Reboot-loop fix (v069i/v069j):** ephemeral↔vault must not spawn `stickllm-vault ensure-addons` / model restore (OOM / kiosk blink). Gateway only flips `session-mode.json`. Vault: no UI `try-restart`, no `--restore-last-model` from unlock add-on start; already-mounted unlock is view-only. Verified in QEMU `E:\stickllm-vm\v068` (8 toggles, `addons_restart=false`).
- *(superseded in tree)* Test/Terminal empty SSH was briefly tried for VM OCR; **0.6.10 tree restores random mint + splash** — see above.
- Vault wizard: after first successful create → enter vault mode → recovery phrase → **System ready**; never re-paint or re-run Vault create (`vaultDone` short-circuits; blob/exists forces unlock).
- Vault wizard unstick: if create Continue hangs after the blob is already unlocked/created, rescue to vault mode or unlock-only (never leave a disabled Continue on the create passcode page); re-detect existing `stickllm-vault.img` before create; poll during long USB create.
- Fresh setup starts at **Open model** (no welcome gate). Returning boots with a vault still unlock-only.
- Welcome wizard intro: drop “when you want” from the offline tagline.
- Open A0 debounce / no auto-open; Enter unlocks like Continue; honest load chip (“first reply takes a long time”).
- **Post-ship hotfix (v069k, tree / stick hotfix — does not rewrite the v0.6.9 ISO):** first Open Agent Zero waits for `/agent-zero/api/csrf_token` only (no force-embed on `running`); embed shim keeps loopback `:5099` under `/agent-zero/`; README + Troubleshooting tip: if Chromium shows 127.0.0.1 refused, Reload desktop then Open Agent Zero again.
- UI cache bust `v069k`.

## 0.6.8 - 2026-11-06
- Agent Zero open sequencing: never open Chat/A0 during first-boot wizard or mid vault-create; open once after System ready / wizard dismiss or vault unlock on returning boot (`stickllm:vault-unlocked`).
- First load without error: show Install/Waiting panel and poll until `/agent-zero/` HTTP is up (`agentHttpReady`) before setting the iframe — never navigate to a dead port (no 127.0.0.1 refused-to-connect on first paint).
- Hard-reload harden: `agentHttpReady` requires `/agent-zero/api/csrf_token` (not HEAD alone); single-flight panel→iframe upgrade; detect splash “Unable to load” / “could not get data” for in-place reload; UI cache bust `v068a`.
- Cap blank/`pair_required` iframe recovery to in-place reloads (max 3); no close+reopen loops.
- Keep prior fix: no vault-mode toast spam from the health poll (`setSessionMode` idempotent / `unchanged`).
- Auto llama warmup: after Activate and after vault unlock restore, fire a real `/v1/chat/completions` ping (no llama remint) so the first Agent Zero message is not stuck on “Calling LLM”; write `llama-warmup.json` with `ready=true` (666 under `/run`, `/tmp` fallback when stickllm cannot create in root:stickllm-llama 775); UI chip shows “Warming up…” while queued/waiting/running.
- Preparing-agent toast removed — caused Agent Zero embed failure (bad screen). No StickLLM “Preparing agent…” UI, no embed `stickllm-a0` prompt postMessage, no gateway `AGENT_PROMPT_BUSY` hooks (`agent_prompt` health field left as unused stub).
- Default llama `ctx_size` raised to **32768** (32K floor) in the baked profile.
- Desktop: boot splash block logo as a quiet deskMode backdrop; Settings hamburger driven by panel width (`.setShell.setNarrow`) rather than viewport alone.

### Later
- Generate splash / SSH test-mode passwords (`stickllm-ssh-bootstrap`) with a stricter OCR-friendly charset (avoid O/0, S/5, I/l/1, B/8, Z/2, etc.); keep length / entropy adequate.
- Optimize entire desktop UI for phones — taskbar, windows, launcher and icons currently do not render well on small viewports. See `docs/UI-PHONE.md`.

## 0.6.7 - 2026-11-06
- Default baked model: **Qwen2.5-7B Instruct Q4_K_M** (~4.4 GB split GGUF on the stick) replaces Qwen3.5-4B; Open model / catalog `base_model_id` / probe default follow it. Q5_K_M stays an optional download (min 10 GB VRAM for 32K headroom). Qwen3.5-4B remains an optional catalog download (not Open default, not baked).
- VRAM tier recommends (one each): **8 GB** baked 7B Q4 · **12 GB** 14B Q4 · **16 GB** 32B Q3 · **24 GB** 27B Q4 · **32 GB** 32B Q4 · **Dual 24 GB** 72B Q3 (CUDA tensor-split; probe sums NVIDIA VRAM). See `docs/MODELS.md`.
- First-boot order: mount SSD and look for an existing vault first; if found, ask passcode only and reuse vault settings (no full re-setup).
- Fresh stick (no vault): first screen is **Open model** with the on-stick base model (Continue loads it, Skip defers); then Network → Storage → Vault → System ready.
- Vault create: enter Vault mode immediately after create; show recovery phrase with checkbox + Continue only (Cancel removed); then System ready — no second passcode prompt / “vault already exists” loop.
- Reboot unlock: busy overlay says **Opening vault** (not “Creating vault”); Creating only for first-time create.
- Vault passcode fields: block browser password-manager save prompts (`autocomplete=off`, readonly-until-focus, masked text inputs).
- Agent Zero: after reboot unlock, clear stale Open / Retry / Open App Store CTAs, start A0, and upgrade the panel to the embed when running (`stickllm:vault-unlocked`); Open Agent Zero waits until running on the first click.
- Remote pair: after a successful pair code, show desktop / Agent Zero without a manual refresh (post-pair status + `startChatAgentPoll` upgrades the Install/Unlock panel to the A0 embed; reload a blank/`pair_required` iframe).
- Desktop icons: click an already-open app (Agent Zero, starters, catalog, panels) to bring its WinBox to the front; restore if minimised — same focus path as the taskbar open-apps bar (no minimise toggle).
- Quiet Agent Zero Chat “Disconnected” / “Reconnected” (and WS polling-fallback) toasts in the `/agent-zero/` embed shim — those are Socket.IO sync churn, including on kiosk loopback; StickLLM’s own toast coalesce never saw them.
- Settings → Devices: remove one-click **Copy password** for SSH (password stays selectable/highlightable).
- Settings: ↑/↓ move between sections; on phone/narrow viewports the section list is a hamburger drawer (not a permanent side list).
- Boot logo: ignore / reset-failed `stickllm-gpu-skip.service` in `stickllm-bootstatus` so intentional skip never paints “! Problem:”.
- `stickllm-gpu-skip`: never fail the systemd unit on empty greps (silences Failed on the StickLLM boot logo).
- Microphone (kiosk + HTTPS): retry getUserMedia a few times on NotAllowed/dismissed prompt; Voice on asks for mic; Voice click or mic button re-triggers Allow; toast site-settings reset when Chromium has Blocked the origin.
- Docs: advertise minimum hardware **16 GB** system RAM + **8 GB** GPU (do not market 4 GB).
- Docs: GPU backends — **AMD:** ROCm and Vulkan; **NVIDIA:** CUDA; **Intel GPU:** Vulkan.
- Docs: Tested hardware — NVIDIA single/dual RTX 3090; AMD single RX 570 / RX 580.

## 0.6.6 - 2026-11-06
- Retire StickLLM Chat chrome and desktop Chat icon; Agent Zero is the only chat window (never mount `#app` into WinBox).
- `/agent-zero/` embed records LAN prompts so open_app (solitaire, calculator, …) opens on the requesting client, not always the kiosk.
- Microphone: remote HTTP→HTTPS redirect when TLS is up; no red embed banner; `Permissions-Policy: microphone=*`; iframe `allow=microphone`; quiet secure-context toast; stickllm/kiosk in `audio` group; VAD via MediaStreamDestination.
- Settings → Devices: SSH user/host/password under the pair code on GRUB Test/Terminal boots (stick screen only).
- Model presets: Minimum 32k / Balanced 64k / Long 128k; fit-check default and context floor 32k (Agent Zero).
- Remote client: coalesce disconnect/pair toasts; slower EventSource backoff; no `window.alert("pair_required")`; EventSource stops when unpaired/hidden.
- First-boot wizard: scrollable Wi‑Fi scan + `wifi_connect` (not `wifi_join`); Continue joins before advance; vault create/unlock flow; starter-model step removed.
- Reboot after setup: detect prior setup via `stickllm-setup.json` / vault location on STICKLLM-DATA (not Chromium localStorage); ask for vault passcode only and restore from vault — do not re-run the full wizard.
- Kiosk Chromium: `--use-angle=gl` on Xfce/X11 (SwiftShader only via `STICKLLM_KIOSK_SW_GL=1`); WinBox inactive filter removed (compositor flicker).
- Agent Zero chat auto-rename: defer from `monologue_start` to `monologue_end` with backoff so utility naming no longer races the busy llama slot (“Utility Model was not reachable”); utility preset disables Qwen thinking (`enable_thinking: false`) so naming gets `content` not empty `reasoning_content`.

## 0.6.4 - 2026-11-05
- Paired LAN Chat embeds Agent Zero same-origin at `/agent-zero/` (thin gateway: HTML/CSS path prefix, splash boot rewrite, fetch/XHR/WS shim; JS bodies untouched).
- Chat iframe uses `/agent-zero/`; pop-out / handoff still uses `:5443` after the stick cert is trusted.
- ETag/`no-store` on rewritten embed responses; loopback Origin on HTTP+WS relay so upstream accepts paired clients.

## 0.6.3 - 2026-11-05
- Agent Zero is an OS-installed docker graph at /opt/stickllm/docker (in filesystem.squashfs); no ISO tar installer; DATA attaches RO layer diffs (no first-boot bulk copy)
- Agent Zero runnable endpoint: RO-bind squashfs layer diffs into DATA docker root (no first-boot full seed copy); Move to SSD materializes explicitly

- First-time setup wizard (network, storage, vault, starter model, tour); re-runnable from Settings.
- STICKLLM-DATA vault first-class; storage_targets + mount unmounted host partitions (never format).
- Downloads prefer SSD models folder; space check before enqueue; failed queue items kept with reason; Stop/Delete soft; partial cleanup.
- Agent Zero ships preinstalled on the stick (docker-seed in squashfs); runs from USB by default with no Install step.
- Agent Zero docker-seed uses overlay2 (not vfs) so the squashfs seed stays ~image-sized; refuse seeds >20GB
- a0_seed builds overlay2 data-root on the live-build volume (/work), not /tmp (Docker Desktop nested overlay fails on /tmp)
- a0_seed must not system-prune the loaded image; refuse seeds <1GB or empty overlay2
- Optional one-time "Move Agent Zero to SSD (faster)" in Settings and first-time setup (progress bar; reversible "Run from stick").
- Agent Zero is the main Chat window; StickLLM thread/composer UI hidden (Models / System / Settings / apps kept).
- Cheap `status_light` / cached model enrich for System monitor.
- Persist journal + dmesg snapshots to STICKLLM-DATA; skip GPUs whose amdgpu init fails (best effort).
- Models list groups non-loadable entries under "Can't load on this system".
- Control hardened against EIO on flaky DATA (discovery + do_POST).
# Changelog

## 0.6.2 (2026-11-05)

Agent Zero reliability first, plus model, GPU and desktop fixes from the 0.6.1
hardware test.

- Agent Zero: install and start no longer hang (bind retry without a DNS
  lookup, MiniLM embedding bundled on the ISO and seeded offline, start order
  fixed); install progress shows real stages; the agent window opens once it
  answers; the agent preset follows the model you activate and waits for it;
  chat spots a reply loop and suggests a bigger model. No typed confirmation
  words anywhere (buttons; a checkbox plus a button for wipes).
- Models: downloads resolve catalog files properly, fail clearly when nothing
  resolves, keep "done" with the real size and show a moving step; split GGUFs
  activate from part 00001; models with an experimental architecture are
  labelled; a crash while loading names the architecture instead of a bare
  exit code.
- GPUs: among Vulkan cards with about the same free VRAM the PCIe x16 card
  wins over an x1 riser; a card can be pinned by PCI address; the context is
  shrunk before a partial offload; cards are named by PCI slot, size and link;
  NVIDIA prep is skipped on machines without NVIDIA cards.
- Boot: the Safe boot entry (GRUB and BIOS/isolinux menu) turns the AMD IOMMU
  off for boards whose USB stops working with it on.
- Desktop: toasts stack with a close button and never replace an error; app
  windows come in front of the Chrome browser window; neutral GPU wording for
  AMD/Intel; the SSH line says "Not connected" until there is a LAN IP.

## 0.6.1 (2026-11-04)

Fixes from the 0.6.0 hardware test.

- Boot: BIOS GRUB uses a text menu (no "insufficient memory") and has a Safe
  boot entry; terminal mode logs in on its own (root console); F10 shows the SSH password and F9 a new pair code (the
  boot screen shows a password only in Test); the SSH line shows the real LAN
  IP in a centred box; a USB 2 port gets a warning.
- Desktop: xfwm4 maximises without a title bar, frame log path fixed, no
  restart loop; the kiosk Power menu powers off after a confirm; the context
  slider no longer draws a white/checkered box.
- Network: the IP shows right after joining Wi-Fi; the Wi-Fi list rescans and
  takes a hidden SSID.
- Storage: the vault can live on STICKLLM-DATA (warning + confirm);
  stickllm-persist accepts USB-transport drives; "Use free stick space" acts or
  says why not; single-drive machines fall back to STICKLLM-DATA with clear
  messages; `stickllm-update` stages a verified ISO (A/B, UEFI boot entries).
- Models: presets follow the VRAM (32K/64K defaults), a fit check before
  loading offers a smaller KV cache or context, one GPU only when the model
  fits with a 10% margin, models on the USB stick sort last with a red
  "Slow USB load" label, and the list refreshes when a vault or drive changes.
- Agent Zero: "open <app>" opens at once from chat; the stickllm-apps skill
  lists every app (add-ons and the browser); new open_url / open_file tools
  show pages in the user's browser; an Agent Zero button next to Web hands the
  message to Agent Zero; the chat model knows whether Agent Zero is there; the
  Agent window offers "Open Agent Zero in a new tab"; Settings > Agent Zero has
  "Unlock all plugins" (on by default, as in 0.5.9) and example tasks.
- Apps: Notepad opens the folder it saved to; Office opens a file from this
  computer right after copying it to vault/Documents.

## 0.6.0 (2026-11-04)

Agent Zero is the one agent stack: the StickLLM chat is the simple view, the
Agent Zero window is the advanced view of the same chats and model.

- Agent Zero image on the ISO (A1): the pinned v2.15 amd64 image is packed at
  build time from sha256-checked registry blobs into a docker-archive split in
  1 GiB parts (`/stickllm/agent-zero` on the ISO, outside the squashfs).
  Install loads it offline (`docker load`, then the config digest is checked
  against the pin); no network is needed. `STICKLLM_A0_BUNDLE=0` builds without
  it, and the stick then downloads it on Install as in 0.5.x.
- Shared chats (A2): Agent Zero's chats live in the active chat store (USB or
  SSD vault) and show in the StickLLM chat list; StickLLM chats open in Agent
  Zero. 0.5.x Agent Zero chats are moved there once.
- Speech (A3): the microphone and read-aloud use Agent Zero's Whisper and
  Kokoro while Agent Zero runs, else the built-in whisper.cpp and KittenTTS.
- Model (A4): Agent Zero's preset follows the model loaded in StickLLM.
- Status (A5): the Agent link shows the phase and progress (loading from the
  stick, downloading, checking, installing, starting).
- Install apps from Agent Zero (A6): "install Node-RED" in Agent Zero installs
  the StickLLM add-on with the same installer as the Apps page (icon, window,
  progress), through the existing desktop bridge; catalog ids only, never
  inside the Agent Zero container. Verified add-ons start at once;
  ONLYOFFICE, ComfyUI and changed or unverified apps still ask on screen. Agent Zero's own
  plugins still install inside Agent Zero.
- Ephemeral/Vault (B3-B5): switching only changes where chats go; it no
  longer stops the model, add-ons, Agent Zero or Docker. Add-ons that need the
  vault start again on return to Vault, and the launcher starts a stopped
  add-on with progress. Chats reappear after Vault -> Ephemeral -> Vault.
  vault-boot.txt follows the real vault state.
- Chat storage (B9/B10): chats in the USB settings vault or the SSD vault
  (both encrypted), with optional newest-wins sync between them.
- Progress (B8): actions that take over 1 s show a progress toast.
- Terminal mode (B1): no desktop or X on tty1 (live-config's startx hook and
  autologin are off), no wait on services before the login prompt, and the
  console shows the real LAN IP (refreshed when DHCP finishes) instead of
  127.0.0.1.
- Displays (B2): with an RX 570 and an NVIDIA card, a monitor on the NVIDIA
  card is found even when simpledrm is present; the Radeon firmware is always
  in the image; Xorg never binds the second card.
- Desktop (B6): the StickLLM desktop window stays borderless on Xfce (the
  frame is removed after Chromium's own state changes and again if it comes
  back).
- Desktop start (B7): a failing Xorg driver no longer costs 30 s before the
  next one is tried; each start phase is timed in /run/stickllm/kiosk.log
  (`STICKLLM_KIOSK_T`).
- Build: the ISO is about 3.2 GB larger (Agent Zero bundle; 16 GB stick or
  larger). The build machine needs ~50 GB free and network once for the
  Agent Zero blobs (cached in `out/cache/agent-zero`).

## 0.5.9 (2026-11-04)

- Agent Zero: upgraded from v2.14 to v2.15 (latest stable, 2026-11-01; tag
  commit ba9b67df0f54; manifest sha256:05d6ab34…28bd8, amd64
  sha256:fb62c7f0…6cde2). An SSD that still has v2.14 shows "Agent Zero is not
  installed yet" until v2.15 is pulled (Install). Ports, the service and the
  llama_cpp provider pointing at the local llama-server are unchanged.
- Agent Zero plugins: all of them are unlocked (the v0.5.4 ban and allowlist
  lock are lifted). The plugin dir is writable and kept across restarts, the
  built-in installer, scanner, validator and plugin skills stay, and the Agent
  proxy no longer refuses plugin APIs.
- Desktop (Xorg): NVIDIA ModulePath conf so the nvidia driver loads; if it
  fails, retry the same card with modesetting. Fallback only picks cards with a
  connected monitor and prefers boot_vga.
- Console font: banner check marks render (no missing glyphs in Terminus).
- Web desktop: Chromium window is borderless with no minimize/close; the Chat
  window has a cyan ghost frame.
- GPUs: a model that fits on one card loads on one card (most free VRAM); it is
  split only when needed (STICKLLM_GPU_SPLIT=always restores the old split).
- Monitor: every GPU (NVIDIA, AMD via sysfs, onboard) with real lspci names,
  VRAM, temp, load, power vs limit, fan, clocks, PCIe and which card holds the
  model; CPU model, threads, uptime; status line; live tok/s and context used.
- Settings > Advanced: allowed GPUs, pin to one GPU, power presets
  (eco / long job / default / boost, reset on reboot) through a narrow sudo
  helper (stickllm-gpu-power); per-model load settings (ctx, -ngl, parallel,
  -ctk/-ctv, --override-tensor, mmap, mlock, GPU pin).
- App agent is off by default and moved to Settings > Advanced (experimental);
  turning it on with no model loaded loads the baked-in Qwen3.5-4B. Solitaire's
  "Back to Apps" link is gone.
- Browser: fixed "[Errno 2] ... runuser" when the vault is locked.
- Settings > Network shows the real IP, interface type and LAN URL (Copy uses
  it); the SSID box is empty unless a network is saved. Settings > System and
  About show live GPU/driver/RAM/storage/llama.cpp values instead of samples.
- Unchanged from 0.5.8: Terminal mode, Test - SSH Enabled password, F10/F9,
  no sway, cage browser fallback.

## 0.5.8 (2026-11-03)

- Boot: fixed tty1 staying on the loading timer. Chat/Local no longer wait on a
  model-download phase, and a `.partial` model file untouched for 5 minutes is
  treated as a dead download in every mode.
- Boot: the loading screen gives up after 2 minutes and prints the old plain
  text output (ready info, URL, SSH password when SSH is on); Chat then opens
  the desktop anyway.
- Terminal mode no longer depends on the loading screen, kiosk, Xorg, gateway
  or llama: SSH info goes into the login banner and tty1 gets a login prompt.
- Test - SSH Enabled (menu 3) shows the SSH password on screen again.
- Loading screen: StickLLM block banner, tagline, version, mm:ss timer, real
  status lines and the F10 / F9 hint; Terminus console font (ASCII fallback).
- Desktop: the full-screen browser kiosk (cage) is back as the fallback when
  Xfce fails; sway stays removed.

## 0.5.7 (2026-11-03)

- Manuals: every App Agent manual (`stickllm_appagent/manuals/`) ships in the ISO.
- Xfce start fixed: Xorg now logs to `/run/stickllm/xorg/stickllm-xorg.log`
  (a kiosk-owned run dir, rotated by StickLLM before each start) instead of
  `/var/log/stickllm-xorg.log`, which an earlier root Xorg left behind and the
  next start could not move. Stale Xorg servers on :0 are killed before a
  start and when the console is restored. Only the chosen GPU is in the Xorg
  config (AutoAddGPU false), AMD-only path unchanged.
- sway, cage and weston are removed (packages, config, session, fallback
  ladder). Xfce is the only desktop; if it cannot start, the console says so
  and shows where the logs are.
- The Xfce desktop now looks like 0.5.6's sway desktop: the StickLLM desktop
  page (bottom bar with vault and model, launcher, Agent, settings windows)
  fills the screen; no Xfce panel or desktop icons. Browser windows are moved,
  sized, minimised and maximised through wmctrl/xdotool.
- Cleaner boot screen: version, elapsed timer and only real status lines. The
  model line shows only while llama is really loading or ready. No pair code
  or passwords at boot on desktop modes (F10 / F9 on the desktop).
- Version 0.5.7 (health endpoint, About, ISO name).

## 0.5.6 (2026-11-03)

Desktop (stick screen)
- The stick's own screen (and PCs booted from the stick) now opens a stock
  Xfce desktop: the Debian Xfce 4.18 packages on Xorg, unmodified and set up
  only through Xfce settings. A bottom taskbar has StickLLM, Browser and the
  StickLLM apps that are installed, plus the window list and clock, on a
  StickLLM wallpaper. StickLLM and each app open in their own windows, all in
  one browser profile, so the app agent can still drive them. It is locked
  down: no terminal, application menu, desktop menu or log-out button; the
  panel, desktop and session cannot be changed or saved.
- If Xfce cannot start, the screen falls back to the sway desktop, then cage
  or weston. `stickllm.compositor=sway|cage|weston` on the boot line skips Xfce.
- Phones and other PCs keep the browser UI (the classic and phone layouts,
  and the in-page desktop below) unchanged.
- No monitor connected: the kiosk waits quietly instead of restarting in a loop.

App agent
- One Qwen3.5-4B serves chat and app control (no second llama-server and no
  hidden helper model). Load or unload the app agent and models yourself in
  Models; there is no 3B, and the recommender suggests the 4B for cards with
  6 GB or more.
- New knowledge packs: Notepad, Calculator and Solitaire (in-browser apps,
  driven over the page's app bridge). Slide pack updated to the 7f3b75e pack.
- No app picker: requests go to the focused or last-used app, to the app you
  name ("... in Notepad"), or a router picks among the installed apps.
- Only installed apps are listed. The app agent helper detects AMD/Vulkan.
- The 4B's thinking is hidden in chat; only the answer shows.
- Node-RED: the editor reloads by itself after the agent deploys or undoes
  (a StickLLM page script set in our Node-RED settings file; Node-RED itself
  is unchanged). New HTTP-in nodes never use "/" as their path.

Vault
- The vault remembers which computer it lives on. On another computer unlock
  fails fast with "Vault is on another computer", with Search for vault and
  Pick drive buttons, instead of probing drives for a long time. Host mounts
  time out after 25 s.

Models
- Models page fixes, including an Unload button for the loaded model.

In-page desktop (browser UI)
- The Chat window is chat only. Settings, Models (with Downloads), App Store
  and Agent (Agent Zero) are desktop apps with icons and Start entries.
- Taskbar: Ephemeral/Vault switch (unlock the vault from its popover; 0.5.5
  unlock/lock fixes kept) and a model button that opens Models, or reads
  "Open Model" when none is loaded.
- Installed catalog apps get a desktop icon and Start entry and open in a
  window; the gateway relay lets only StickLLM's own pages frame them. Apps
  that cannot be framed pop out into a Chromium window.
- Browser opens a real Chromium window on the stick's screen (own RAM profile,
  downloads only into the unlocked vault, blocked while locked).
- The stick's screen now runs a real floating desktop. The kiosk uses the
  stock Debian sway compositor (MIT, unmodified, our own config only) and
  falls back to cage. The StickLLM desktop is full screen with no browser
  chrome. Browser and app pop-out windows float above it at the size the
  desktop asks for: move, resize, minimise to the taskbar, restore, maximise
  and close (taskbar click or right-click, Super+Down/Up, Alt+F4). There is no
  terminal, menu or exit binding.
- Classic and phone layouts are unchanged.

## 0.5.5 (2026-10-30)

App agent
- Chat can drive ONLYOFFICE slides and Node-RED through the app agent
  (stickllm-appagent: request -> checked plan -> actions, with Undo). It uses a
  dedicated Qwen3.5-4B llama-server on 127.0.0.1:8796; the 4B Q4_K_M model is
  baked into the image at /opt/stickllm/models/appagent. The Qwen2.5-3B stays the
  default small chat model. ONLYOFFICE's Plugins tab is hidden.
- Node-RED: the agent never shadows the editor's own routes, reloads the open
  editor tab after a deploy and checks the real HTTP endpoint (hello world -> /hello).

Desktop
- New desktop layout (Auto/Desktop/Classic) with WinBox 0.2.82 windows, a start
  menu, taskbar and status tray; narrow windows keep the tabbed layout.
- Minesweeper starts as a game (solver overlay off); Files follows the StickLLM
  theme; Notepad's Back to Apps link tidied.

Models
- The baked Qwen3.5-4B shows as installed in Models, loads and chats, and cannot
  be deleted. Load works for Hugging Face hits already on disk; installed models
  sort first in search.
- Model probe no longer leaves "Recommended" blank on a machine with nvidia-smi
  but no GPU/driver.

Chat and vault
- A thinking model's reasoning is hidden (Show reasoning, collapsed).
- No more "No vault set up" / Ephemeral flash right after unlock, and the Vault
  tab no longer stays lit after lock. /api/health reports the USB settings as
  present-locked for a vault that is not yet bound.

## 0.5.4 (rc2, 2026-10-28)

Chat and vault (rc2)
- The Ephemeral/Vault tabs follow the vault: Ephemeral is highlighted whenever the
  vault is locked (first load included), Vault only after a successful unlock, and
  Ephemeral again on lock. /api/health reports "ephemeral" while the vault is locked.
- Lock (Ctrl+Shift+L, the lock buttons, switching to Ephemeral, or a lock from
  anywhere else seen by the status poll) clears the screen: transcript, chat list,
  saved-chat titles, drafts, attachments, in-memory history and the app tabs this
  page opened. Ephemeral chats are cleared too. Any reply in progress is stopped.

## 0.5.4 (rc1, 2026-10-28)

Apps
- Catalog shows each app's real name with its short tile name in a bright colour
  (for example **ONLYOFFICE** · Office, **Tasks.md** · Tasks, **Paisa** · Budget,
  **Trilium** · Notes), hidden apps included. ComfyUI and Node-RED keep their own names.
- Removed Radicale. Vikunja replaced by Tasks.md 3.3.0 (Markdown kanban, built once
  offline at install); Actual Budget replaced by Paisa v0.7.8. Old data folders are
  not migrated.
- Installing Tasks.md or Paisa no longer loops on "Pool overlaps": an unused
  network left by a retired app on the same subnet is removed first (only empty
  stickllm-* networks on that exact subnet).
- Trilium opens with no login (gateway pairing and the vault are the lock) and sets
  itself up automatically on first start.
- ComfyUI is installable. It uses the NVIDIA GPU when present (warns below 6 GB free
  VRAM) and otherwise runs on the CPU.

Office (ONLYOFFICE)
- New asks for a file name, defaulting to "Document/Spreadsheet/Presentation YYYY-MM-DD".
- Rename from the file list or from the editor title (open editors keep saving to the
  renamed file); Save copy as from the list or the editor's File menu.
- Downloads panel lists the vault Downloads folder with "Open in Office" (imports a copy).

Agent Zero
- Third-party plugins removed on every path, kiosk console included: empty allowlist
  enforced by the ISO build, plugin installer/scanner/validator deleted in the container,
  plugin badges removed. `verified.json` lists no plugins.
- Chat shows a friendly "No AI model is loaded yet" message instead of a connection
  error, in both the StickLLM chat and the Agent Zero chat.
- The llama relay no longer drops slow responses after 10 s (the connect timeout used
  to stay on the open socket).

System
- Missing AVX and low VRAM are warnings (Monitor card plus a one-time notice), not failures.
- Vault unlock: no brief "no vault set up" flash before the status loads; if the unlock
  form cannot be shown, an inline error says why. Switching to Vault mode on a locked
  vault asks for the passcode instead of saying "No vault yet".
- Text to speech falls back to a one-shot load when the resident voice cannot start.
- Build: `STICKLLM_OUT_DIR` may be an absolute path (for example `/e/stickllm-build/out`)
  so the ISO can be written to another local drive when C: is short on space.
