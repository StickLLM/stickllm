# Cursor chat history: "Privacy AI USB image build" (StickLLM → Agent Zero)

This file summarizes the important parts of the Cursor agent chat that built StickLLM, from Oct 7 to Oct 25, 2026.
It is grouped by topic, not by date. Secrets are left out on purpose: no passwords, pair codes or tokens.

- Source chat: `C:\Users\peter\.cursor\projects\c-Users-peter-stickllm-vault-wt\agent-transcripts\678605c3-21e4-464f-9ad2-99ec873815b4\` (jsonl plus `subagents\`).
- An older chat with the same opening message is `94629648-bd26-4f61-b076-2fda739a0560`. It was not used here.
- Worktree: `C:\Users\peter\stickllm-vault-wt` (the main repo is `C:\Users\peter\stickllm`).
- GitHub: `StickLLM/stickllm`.

---

## 1. What was built and why

- **StickLLM** is a Debian live USB. It boots any AMD/NVIDIA PC into a private, offline local-LLM appliance.
  - It runs `llama-server` (llama.cpp) behind a Python gateway with a web chat UI.
  - It has an encrypted vault on the host SSD, so chats and models persist without touching the host OS.
  - The original target was AMD with 32 GB RAM and an RTX 3090. The lab server, at `192.168.72.70`, has two 3090s.
- **Release line:**
  - v0.2: pairing, Models menu, USB DATA catalog.
  - v0.3.x.
  - v0.4.0, v0.4.1 (voice) and v0.4.2 (voice fixes and the USB settings partition).
  - Published ISOs and checksums are immutable. Never overwrite `out/v0.x.y/` or `checksums/v0.x.y.sha256`.
  - The final v0.4.2 sha256 is `3a50eb56…72ef7`. The old, unpublished v0.4.2 hash `f31b5353…0875` must not be uploaded.
- **Agent Zero branch, `stickllm-agentzero`:**
  - It adds Agent Zero (`agent0ai/agent-zero` v2.14, pinned by digest `sha256:307a2cef…30fd`) on top of StickLLM, backed by the local llama-server.
  - The v0.4.2 ship commit was tagged `pre-agentzero-backup` (`d573118`) before the branch was cut.
  - ISOs are written to `build-agentzero/`:
    - `stickllm-agentzero-v0.1.iso` (sha `56684c4a…`).
    - `stickllm-agentzero-v0.2.iso` (sha `cc5d093a…75c8`, 4,127,195,136 bytes). This one was flashed on Oct 25 at 7:29 AM ET.
- **Why Agent Zero:** it is meant to be the first app users install, so it can install and configure the other apps. For that reason it stays **separate** from the Apps catalog UI. It is only the first row in the catalog for install.

## 2. Architecture and key decisions

- **Gateway** (`overlay/usr/local/bin/stickllm-gateway`):
  - Serves HTTP on :80 and HTTPS on :443 with a self-signed certificate.
  - It is the only LAN entry point.
  - Proxies to llama `127.0.0.1:8080`, control `127.0.0.1:8091` and files `127.0.0.1:8096`.
  - A second TLS listener on **:5443** proxies Agent Zero 1:1 to `127.0.0.1:5099`.
  - A0 cannot live under `/agent`, because its service worker has scope `/` and it uses root asset paths.
- **Control daemon** `stickllm-control` (:8091): model load and unload, vault actions, settings, and HF token storage.
- **Agent Zero runtime** (`overlay/usr/local/lib/stickllm_agent.py`, `stickllm-agent` CLI, `stickllm-agent.service`):
  - The image is **not baked into the ISO**. The user installs it explicitly from the Apps catalog or from Settings → System, which runs `stickllm-agent install` and shows the docker pull log.
  - The Docker data-root is `<vault root>/stickllm-docker`, next to `models/` on the host SSD. It needs about 12 GB free. `docker_data_root()` refuses paths inside the vault.
  - The folder is found by `discover_models_dir()`, in this order: `STICKLLM_MODELS_DIR`, then `/run/stickllm/models-dir.json`, then `/run/stickllm/vault.json`, then a search of `/mnt/stickllm-host`.
  - "Installed" means only `image_present()`, a `docker image inspect` of the pinned digest. Unlocking the vault never pulls. After an install, unlock auto-starts the agent through `start_agent_addon()` in `stickllm-vault`.
  - Memory, work, logs and state live in the vault at `vault/addons/agent-zero`. Settings and keys live in `/mnt/stickllm-settings/agent-zero`.
  - The v0.1 image stored inside the vault (`/var/lib/stickllm/vault/docker`) is **not** detected by v0.2, so you must reinstall.
  - The container `stickllm-agent-zero` runs on its own bridge, `stickllm-agent` / iface `stickllm-a0`, network `172.30.0.0/24`. The host is `172.30.0.1` and the container is `172.30.0.2`.
  - The container has `no-new-privileges`, no `apparmor=unconfined`, and `NVIDIA_VISIBLE_DEVICES=void`, so it never takes GPU memory from llama.
- **Bridge services:**
  - **Llama relay** on `172.30.0.1:8080`.
  - **Static apps server** on `172.30.0.1:8081` (`/apps/<id>/` only, read-only).
  - **open_app control** on `172.30.0.1:8082` and `127.0.0.1:8082`.
- **Firewall** (`nft_apply()` / `nft_ruleset()`):
  - Only `iifname stickllm-a0 → 172.30.0.1 tcp {8080, 8081, 8082}` is allowed. Other host ports and all RFC1918 ranges, including the LAN `192.168.72.x`, are dropped. Internet access is allowed.
  - Loopback is accepted so the host can run relay health checks.
- **Console browser** (`stickllm-kiosk`):
  - Chromium runs as user `stickllm` (so the sandbox works) under Cage/Weston.
  - It is a normal maximized window with the **address bar and tab strip kept**. It does not use `--kiosk` or `--app`, and a policy blocks fullscreen.
  - StickLLM opens at `http://127.0.0.1/`, and Agent Zero runs in its own tab.
- **Apps desktop** (`ui/apps/*`, `stickllm_apps.py`, `docs/APPS.md`):
  - Installed tiles: Files, Notepad, minesweep, Calculator, Media, Monitor and Tetris.
  - **Install apps** opens the catalog: ONLYOFFICE, Paperless-ngx, Immich, ComfyUI, n8n and others. Each is honestly marked "not available yet", and none fakes a successful install.
- **Voice** (in StickLLM, not A0):
  - Speech-to-text is whisper.cpp `tiny.en`, running as `whisper-server` on `127.0.0.1:8178`.
  - Text-to-speech is KittenTTS mini 0.8 ONNX, voice Bella.
  - Both are CPU-only. Their weights are in `/opt/stickllm/speech`, not in the vault. They stay loaded only while Voice is on.

## 3. Files and functions touched (main ones)

- `overlay/usr/local/lib/stickllm_agent.py`:
  - `nft_apply`, `nft_ruleset`, `prepare_portable` (writes `settings.json` and `model-config/presets.yaml`), `docker_data_root`, `discover_models_dir`.
  - ALLOWED_ORIGINS builder and open-app client (`_OPEN_URL`, token file `/stickllm-open-app.token`).
- `overlay/usr/local/bin/stickllm-agent`: `cmd_install`, `cmd_run`, `image_present`, `write-status`. Status is kept in `/run/stickllm/agent-status.json`.
- `overlay/usr/local/bin/stickllm-gateway`: :5443 listener, the "Back to StickLLM" pages, host-header forwarding for the A0 websocket, and open-app SSE/websocket events for paired browsers.
- `overlay/usr/local/bin/stickllm-vault`: `start_agent_addon()`, plus the settings-partition format on unlock.
- `overlay/usr/local/bin/stickllm-kiosk`: Chromium flags.
- `stickllm-files` (:8096): a small Python file manager with Home, Vault and SSD apps roots.
- `ui/app.js`, `ui/index.html`, `ui/style.css`: chat UI, voice, Apps desktop and catalog, pairing. Bump `app.js?v=…` when it changes.
- `ui/apps/{minesweeper,notepad,tetris,calculator,media,monitor,files}`:
  - Vendored upstream apps keep `LICENSE` and `SOURCES.txt`:
    - JSMinesweeper `c30bd65`;
    - text-editor `e3a33c2`;
    - javascript-tetris `e5c0c42`;
    - SolitaireLib `6342e1b`, since removed.
- `stickllm_apps.py` + `docs/APPS.md`: catalog fields `disk_gb`, `ram_gb` (min/rec), `vram_gb`, `gpu` and `note`, shown as "Disk X GB · RAM X GB · GPU … · approx."
- `tests/test_agent_zero.py`: unlock does not install; the 12 GB check; no `/agent` rewrite; unpaired 401; nft syntax check.
- Systemd units in `overlay/etc/systemd/system/`: `stickllm-{agent,bootstatus,console-setup,control,files,kiosk,kitten,llama,local,nvidia,ssh,ui,usb,whisper}.service`.

## 4. Ports

| Port | Bind | What |
|---|---|---|
| 80 / 443 | LAN | StickLLM gateway (HTTP / HTTPS, self-signed) |
| 5443 | LAN | Gateway TLS proxy to Agent Zero (pairing required, otherwise 401) |
| 5099 | 127.0.0.1 only | Agent Zero web UI (never on the LAN) |
| 8080 | 127.0.0.1 | llama-server (`--jinja`); `/metrics`, `/health` |
| 8080 / 8081 / 8082 | 172.30.0.1 | A0 bridge: llama relay / static apps / open_app control |
| 8082 | 127.0.0.1 | open_app control (console side) |
| 8091 | 127.0.0.1 | stickllm-control |
| 8096 | 127.0.0.1 | stickllm-files |
| 8178 | 127.0.0.1 | whisper-server (only while Voice is on) |
| 22 | LAN | SSH, test boot mode only |

## 5. Auth, tokens and pairing (design only, no values)

- **LAN pairing:**
  - The stick shows a 6-digit pair code. A browser exchanges it for a Bearer session token.
  - Pairing is rate-limited (`pair-rate.json`), and **F9** makes a new code (`pair-remint.json`).
  - The UI re-checks pairing on refresh and before Loading.
  - Every LAN API call, including :5443, needs a paired session. Unpaired calls get 401.
- **Agent Zero login is disabled on purpose.** The gateway's pairing is the only auth, so never add a second A0 password.
  - ALLOWED_ORIGINS is built at start from the current non-loopback IPs: `https://<ip>:5443` and `*://<ip>:*`, plus localhost, 127.0.0.1 and the 172.x bridges.
- **open_app token:**
  - A random token is mounted into the container at `/stickllm-open-app.token`.
  - Calls without the token get 401, unknown app ids get 400, and the app ids are allowlisted.
  - Never commit or print the token.
- **A0 → llama:** provider `llama_cpp`, api_base `http://172.30.0.1:8080/v1`, a dummy key, ctx 32768, timeout 90 s. Settings are merged so the user's own edits are kept.
- **Hugging Face token** is stored by stickllm-control (`hf-token`) and only used for model downloads.
- **Vault** is an encrypted image file, `stickllm-vault.img`, on the host SSD under `/mnt/stickllm-host/...`.
  - A 256 MB USB **settings partition** is claimed raw on first boot and formatted with the vault key on unlock. It mounts at `/mnt/stickllm-settings`.
  - Existing vault: Storage & Vault → mount SSD → search → attach → unlock.
- **SSH test mode:** boot menu "3 Test - SSH Enabled". A random per-boot password for user `stickllm` is shown on the console; **F10** or "Show SSH password" reveals it.
  - The host key changes after every reflash, so accept the new key for that host only.

## 6. Hotfix and build workflow

- **Iterate over SSH, not ISOs** (`docs/DEV-WORKFLOW.md`):
  1. Boot the stick in test SSH mode.
  2. Read the password from the console. The user often sends a photo of it.
     - Pass it through the `STICK_PASS` env var or a temp file outside the repo, never on the command line.
     - Read photos carefully: a lowercase j drops below the baseline and has a dot.
  3. Copy changed files from Windows with paramiko or plink/pscp into `/tmp/stickllm-hotfix/<overlay path>` (for example `/tmp/stickllm-hotfix/opt/stickllm/ui/app.js` or `/tmp/stickllm-hotfix/usr/local/bin/stickllm-control`).
  4. Run `sudo -n stickllm-hotfix [unit…]`. It is in sudoers NOPASSWD. It installs `usr/local/bin/stickllm-*`, `usr/local/lib/stickllm_*.py`, units and UI files, strips CRLF, runs daemon-reload and restarts the named units.
  5. Restart `stickllm-ui` only if the gateway must reload.
- **Standing hotfix rules:**
  - Don't restart `stickllm-llama` unless told; it was often left stopped or running on purpose.
  - Don't stop `stickllm-agent` while it is active.
- **Clean ISO only at the end of a batch:** `./scripts/build.sh` (live-build in Docker), using `STICKLLM_VERSION`, `STICKLLM_ISO_NAME`, `STICKLLM_OUT_DIR` and `STICKLLM_ISO_PATH`.
  - Never patch an ISO.
  - The in-build integrity check rejects truncated images (v0.3.5 was truncated, so never flash it).
  - A build takes about 20 minutes. It must fit a 16 GB stick.
- **Flash:**
  - Use only the Samsung Type-C USB, serial `AA00000000000489` (usually disk 2). Re-check `Get-Disk` first.
  - Use elevated `C:\Python314\python.exe out\safe-flash-samsung-auth.py` through a wrapper. The wrapper must refuse any other serial, disk 0 (WD_BLACK NVMe), disk 1 (Seagate `NA8TPCBG`) and any hash mismatch.
  - Never partition or format host drives.
- **Git:**
  - Work only on `stickllm-agentzero`, and confirm `git branch --show-current` before each commit.
  - Never touch main or master. Commit from PowerShell with a here-string. Don't change git config or skip hooks.
  - Push only this branch, and don't tag or publish until the user has tested on hardware.

## 7. Bugs found and fixed

- **A0 stuck on "starting":** `nft_apply` used `destroy table`, which needs nftables 1.0.8 or later; Debian 12 ships 1.0.6.
  - Fix: `add table` / `delete table`, then the table definition. Loopback was also allowed for the relay health check.
  - nft errors are now surfaced to the tile (`75e170c`).
- **A0 hung on every question:**
  - `settings.json` had no chat or utility model, and the preset model name was only the filename.
  - Also, the gateway rewrote `Host` to 127.0.0.1:5099, so the socket.io websocket returned 403.
  - Fix: merge the model fields; forward the browser Host (websocket now returns 101); `HF_HUB_OFFLINE=1` with MiniLM cached in the vault.
  - "2+2" now answers in 2.35 s (`b477882`).
- **open_app played on the kiosk instead of the user's PC:** every `/api/ui/events` subscriber got every event. The kiosk always auto-opened and its app page answered `app_state`/`app_act`, while the desktop only showed a toast.
  - Fix: events go only to the target screen, which is the LAN browser that used Agent on `:5443` in the last 120 s (or has an Agent websocket open), else the kiosk. Remote tabs now try `window.open` and fall back to the toast.
  - `app_state`/`app_act` fail fast with `409 app_not_open` when the target has no page for that app, and never fall back to the kiosk. See ARCHITECTURE-AGENTZERO.md, open_app.
- **open_app still failed on the PC with pop-ups "allowed":** kiosk.log showed every open_app go to the PC (`target=192.168.72.76`) but always `result=toast-shown`, and no `?app=solitaire` page ever subscribed. `window.open` from an event (no click) in a background tab was still refused, and the toast sat in the hidden tab.
  - Fix: when `window.open` fails, the app opens inside the StickLLM tab (iframe named `stickllm-<id>`, result `embedded`), and the hidden tab flashes its title and shows a notification if allowed. `/apps/*` allow `frame-ancestors 'self'`.
- **Pop-up opened but showed `{"ok": false, "error": "pair_required"}`** (also right after re-pairing): the paired tab's Bearer worked, but the `/apps/solitaire/` load carried no valid `stickllm_pair` cookie. That cookie is set by script and shared by every StickLLM tab on the host (http/https, both ports), so another tab without the token clears or overwrites it. `/apps` auth itself was unchanged by the recent fixes.
  - Fix: app pages get a one-time ticket (`/api/ui/app-ticket`) swapped for an HttpOnly `stickllm_apps` cookie (limited to `/apps/*` and the app's own stream/replies). LAN browsers now always open apps in the in-page panel (no pop-up attempt); "Open in window" pops out on a click. Kiosk unchanged.
- **"Open in window" made the app vanish:** the panel iframe and the pop-out target were both named `stickllm-solitaire`. Chrome resolves a named target to a same-named iframe first, so the click navigated the iframe (kiosk.log: `seen result=opened`, `disconnect app=solitaire`, `loaded`, `connect`) and closing the panel then removed it.
  - Fix: agent open_app now does exactly what clicking the desktop icon does, on kiosk and LAN browser: `window.open(icon.href, icon.target)`, a new tab named `stickllm-<id>`. If that is blocked, a toast or notification button "Open in new tab" runs the same open on one click. The in-page panel is a last resort only (iframe `stickllm-embed-<id>`). The URL ticket was replaced by `/api/ui/apps-session`, which sets the same HttpOnly `stickllm_apps` cookie from the paired tab.
- **Agent open_app never reached the kiosk** (clicked apps worked): kiosk.log showed every open_app as `published ... target=192.168.72.76 reason=agent_lan`. Any LAN browser with an Agent tab open (polls or websocket) counted as driving Agent, while the kiosk's Agent window talks to `127.0.0.1:5099` directly and could never win.
  - Fix: target only a LAN browser that sent a chat message (`/message_async`) in the last 300 s, else the kiosk; `app_state`/`app_act` follow the screen the app was opened on.
- **Minesweeper asked from the desktop opened on the kiosk:** kiosk.log showed `target=kiosk reason=no_lan_agent`. Agent Zero's UI posts chat to `/api/message_async`, but the gateway only matched `/message_async`, so the desktop's chat was never counted.
  - Fix: match `/api/message_async` and `/api/message`, and log `STICKLLM_AGENT_PROMPT`. The target is now the sending device (the `stickllm_device` cookie, else its IP), so any paired phone, tablet or PC gets the app it asked for.
- **Remote PC rejected by A0** ("Origin … not allowed"): ALLOWED_ORIGINS lacked `:5443` (`ecf0975`).
- **Unlock and Agent page loop:** the back link on :5443 went to `/` on the same port.
  - Added a "Back to StickLLM" bar, and the Agent link now opens in a new tab (`a4d3a82`).
- **Console browser:**
  - The fullscreen flag hid the tabs.
  - `--no-sandbox` produced a warning bar (`d3bee1d`).
  - Later `--ignore-certificate-errors-spki-list` and `--allow-insecure-localhost` produced an "unsupported flag" bar. The flags were removed (`56e9429`).
- **Starter apps all broken at first:** the gateway CSP only allows scripts from the stick itself, and inline scripts were blocked.
  - Moved the scripts into files, fixed the Install-apps menu so an outside click or Escape closes it, and fixed Minesweeper contrast and the right-click double toggle.
- **Voice:**
  - The mic sent an empty 777-byte clip for about 2 days. Fixed by keeping the samples, and a second click now stops and sends.
  - tiny.en sometimes hears only "you", which is dropped.
  - Empty TTS is retried once and then shows an error.
  - A new question cancels the old reply.
- **Models:**
  - The context slider now uses the GGUF context length and VRAM fit instead of a 32K cap. CPU stays capped at 8K.
  - Multi-GPU fit counts every shard; before, it measured only part 1 of a 119 GB model.
  - The time-based load bar replaced a fake 30% timer.
- **UI:**
  - Paste-image inserted the image twice.
  - Enter is debounced, and a Stop button was added.
  - The About link is `http://stickllm.org`, because 443 times out.
  - Advanced/Preset controls also show on the catalog view.
  - A Vision tag and filter were added; a grey tag downloads the mmproj.
  - Vault chats can be deleted.

## 8. Things that failed or were dropped

- Homemade Minesweeper and Solitaire were replaced with vendored upstream apps. **Solitaire was then removed**: the user called it the worst version they had ever played.
- Tiny File Manager could not be used because the image has no PHP. FileBrowser was rejected because it cannot keep a locked vault out of its root.
- Vendored Tetris: line clear did not happen in automated play (rows stayed at 0). This is not confirmed as a real bug.
- A0 answering 12*34 through the calculator app took 139.7 s. "start minesweeper" took 7.2 s overall, but the tab opened in 0.026 s.
- Several hotfix attempts got "SSH refused / timed out" because the stick was rebooting or reflashed. The live checks for the v0.1 and v0.2 Agent Zero builds were reported as NOT RUN.
- A0 Kokoro/Whisper vs. StickLLM Kitten/whisper.cpp: the decision was to **keep StickLLM voice** on the chat page.
  - Kokoro sounds better but A0's loop is slower and has no token cap.
  - Switching is a possible later step.

## 9. Open TODOs and known issues

- **Rebuild the A0 ISO.** The fixes since `stickllm-agentzero-v0.2.iso` (`a4d3a82` … `df7b4ce`) exist only as hotfixes on the running stick and in git. A freshly flashed v0.2 stick does not have them.
- **A0 app hooks:** `window.stickllmApp` describe/state/act, built in `bb11ab4`. Agent Zero plays a StickLLM app in the visible tab with `open_app`, `app_state`, and `app_act`.
- **Catalog apps** (ONLYOFFICE, ComfyUI, Immich, …) have no installers yet. The requirement figures are "approx." until measured. Only A0's disk use (4 GB) is measured.
- **Attachments:** ODS/ODT/ODP are not converted to text. Scanned PDFs need a vision model or OCR.
- **The mic needs HTTPS** (a secure context), including over RDP.
- **Voice:** tiny.en accuracy is weak. Talk-over barge-in is not supported.
- **Agent Zero needs reinstalling on each new stick.** `/var/lib/stickllm/vault/docker` from `3db2ac0` is not detected. The image is re-pulled onto the host SSD data-root. Do not point dockerd back at the vault.
- **v0.4.2 publishing:** commit `d573118` is on the pushed branch `fix/multi-gpu-layer-fit`, and the ISO is for Drive upload. Confirm the tag and release state before publishing.
- **Uncommitted worktree changes:**
  - The `tests/fixtures/*` (docx/xlsx/pptx/zip/docm) files are modified.
  - `build-agentzero/` is untracked.
  - Leave both alone unless the user decides.

## 10. User preferences and standing instructions

- Say **FINISHED** when a task is done (hard rule). Start reports with it.
- **Never use OneDrive paths.** Never commit `.cursor/rules/no-onedrive.mdc`, ISOs, model binaries, scratch `out/_*.py`, secrets or `__pycache__`.
- No commit, tag or push until the user has tested, unless they ask. Then push the feature branch only.
- **Never print the stick SSH password**, pair codes or tokens.
- Flash only the Samsung Type-C stick after checking its serial. Never write the NVMe or the Seagate.
- Test it yourself in the browser before claiming it works. The user rejects "should work" claims, so re-verify claims from earlier passes.
- If stuck, use a smarter model.
- Don't rewrite vendored apps. The only allowed changes are offline fixes, a "Back to Apps" link and the title/icon.
- Keep the console address bar and tabs. Remove any Chromium flag that triggers a warning bar.
- Agent Zero stays separate from the Apps UI. Install it from the catalog's first row; its icon and sidebar entry appear only after install.
- Voice models stay in a plain folder (`/opt/stickllm/speech`), not in the vault.
- Use plain-language explanations with concrete numbers (times, hashes, sizes).
- The minesweeper desktop label is exactly **minesweep**, centred; the URL id stays `minesweeper`.
