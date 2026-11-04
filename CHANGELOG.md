# Changelog

## 0.5.9 (2026-11-04)

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
