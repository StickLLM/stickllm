# Pending for v0.8.3

Post-**v0.8.2** punch list. Do not cut/flash until bake confirms these. Shipping tag/ISO must be a **new** name (`v0.8.3` / `StickLLM-v0.8.3.iso`) — never overwrite `v0.8.2`.

**Stick swap recovery (live hotfixes vs baked):** see **[HOTFIX-AFTER-STICK-SWAP.md](HOTFIX-AFTER-STICK-SWAP.md)** — every live kiosk fix that must be re-applied after putting in a new stick, plus what is already in the v0.8.2 ISO.

## Must bake (in tree / lab-hotfixed)

| Item | Status | Notes |
|------|--------|-------|
| **`find_mmproj` family-name match** | In tree on `release/v0.8.3`; lab-hotfixed | When several mmproj files share a models dir, match by family name (e.g. Qwen3VL-8B ↔ `mmproj-Qwen3VL-8B-…`). Do **not** pick largest leftover (e.g. VL-3B mmproj for Qwen3-VL-8B). Also adds Qwen3-VL mmproj fallback repos. Unit: `tests/test_v053.py::test_c_find_mmproj_prefers_matching_family`. Push: `out/_hotfix_mmproj_match.py`. |
| **Agent Zero `vision` follows active mmproj** | In tree; lab-hotfixed | `stickllm_agent` was hardcoding `chat_model_vision: false` / preset `vision: false`, so A0 never sent images even when StickLLM chat + llama-server multimodal worked. Now `_model_vision()` / `_mmproj_path()` drive `model_settings`, `preset_text`, and plugin `config.json` on sync. Unit: `tests/test_agent_zero.py` vision asserts. Push: `out/_hotfix_a0_vision*.py`. |
| **Agent Zero auto-embeds image attachments** | In tree; lab-hotfixed | StickDroid/phone uploads landed as A0 `usr/uploads/*.jpg` but the agent only saw filenames and replied it can’t analyze images. `stickllm_apps` `monologue_start/_20_stickllm_attach_images.py` injects `image_url` history parts when chat `vision: true` (works even when the Phone-app “plain text” prompt skips `vision_load`). Verified on stick with `39.jpg` → “screwdriver”. Unit: `tests/test_agent_zero.py` attach-images asserts. Same agent push as vision flag. |
| **Chat vision budget no longer drops photos** | In tree; lab-hotfixed | `stickllm-convert` `_drop_oversize_images` was tokenizing each `data:image/…` URL as **text** (~37k tokens for a ~50 KB JPEG), so the 60% attachment budget dropped every real photo and the model answered “no image was provided.” Now uses fixed `IMAGE_TOKEN_ESTIMATE` (1024) + length cap `IMAGE_URL_MAX_CHARS` (180k, matches gateway sanitize). Browser UI still shrinks pastes/attaches (`IMAGE_URL_MAX` 70k); StickDroid shrinks on-device. Unit: `tests/test_attachments.py` photo-budget assert. Push: `out/_hotfix_vision_budget.py`. |
| **Apps desk Terminal icon** | In tree; lab-hotfixed on `192.168.72.50` | Desk/Apps icon (with Files/Browser) opens a real Linux terminal via `terminal_open` (`xfce4-terminal` → `kitty` → `xterm`). Bake adds `xfce4-terminal` + `xterm` to `stickllm.list.chroot`. Loopback UI only. Unit: `tests/test_desktop.py` + `tests/test_v056_desktop.py` terminal asserts. Push: `out/_hotfix_terminal_icon.py`. |
| **Terminal minimises to StickLLM bar** | In tree; lab-hotfix | Native terminal skipped the WinBox taskbar. Tracked like Browser (`terminal_status` / `terminal_window`, WM_CLASS `stickllm-terminal-<id>`). Desk bar minimises/restores/closes. Push: `out/_hotfix_terminal_taskbar.py`. Unit: `tests/test_v056_desktop.py` terminal status/window asserts. |
| **XFCE Desktop Terminal launcher** | In tree; lab-hotfixed | Trusted `~/Desktop/Terminal.desktop` for kiosk user (`stickllm-kiosk` + `stickllm-xfce-session` copy from `usr/local/share/stickllm/desktop/`). No xfdesktop (StickLLM web desk is the screen). Unit: `tests/test_v056_desktop.py` desktop launcher asserts. Same Terminal hotfix script. |
| **Experimental UI copy cleanup** | In tree; lab hotfix `out/_hotfix_exp_copy.py` | Drop “3 November 2026” / Debian-13 scare copy from Experimental tab + offer notes. Keep OS-major gating for NInfer without scare wording. |
| **SSH password Copy button** | In tree; lab hotfix `out/_hotfix_ssh_copy.py` | Devices / F10 SSH block: **Copy** next to password (clipboard API + `execCommand` fallback) so Terminal paste works without selecting text. Loopback only. |
| **SSH password → Terminal paste** | In tree; lab hotfix `out/_hotfix_terminal_paste.py` | One-click **Paste into Terminal**: X11 CLIPBOARD (`xclip`) → focus Terminal → **Ctrl+Shift+V** → **Enter** (same path as manual paste; avoids `xdotool type --window` / XSendEvent). Also: Test/Terminal `stickllm-ssh` sudoers allows password `ALL` (helpers stay NOPASSWD). Units: `tests/test_v056_desktop.py`, `test_ssh_bootstrap_testmode.py`, `test_live_user_lockdown.py`. |
| **Paste empty-clipboard + Terminal z-order** | In tree; same hotfix | Root cause: `subprocess.run` killed `xclip` on timeout but still reported OK → empty paste → sudo **Sorry, try again.** Fix: leave xclip owner alive + verify selection; paste prefers existing/orphan Terminal (not a new shell after control restart). Desk is BELOW native X11: `wm.focus` now `yieldNative()` so Terminal minimises when Settings/Agent/etc. is clicked. |
| **About website URL → stickllm.com** | In tree; lab hotfix `out/_hotfix_about_domain.py` | About → Website link/label `stickllm.org` → `stickllm.com` (`ui/index.html`). |
| **Setup vault: pick USB HDD / other drive** | In tree; lab hotfix `out/_hotfix_setup_usb_storage.py` | First-boot Storage used `storage_targets`, which skipped any disk with `RM=1` / `HOTPLUG=1` — so USB HDDs (lab Seagate / `STICKLLM-EXT`) never appeared. Now offers USB + internal unmounted ordinary FS (not the boot stick), clearer labels, Refresh, Mount stays on Storage step, Vault step **Choose a different drive**. Unit: `tests/test_v083_setup_usb_storage.py`. Never formats. |
| **LAN browser desk open (A0 / Minesweeper)** | In tree; lab hotfix `out/_hotfix_browser_open_apps.py` | Pair gate + single-click wall open on the **requesting** LAN browser (`needsLanPair` / `ensurePaired` / `primeAppsSession`; cache `?v=v083browser`). Unpaired → toast pair, not blank 401 iframe. After flash: hard-refresh + pair. HOTFIX checklist **17b**. |
| **Agent Zero first-start delay / “hang”** | In tree; lab hotfix `out/_hotfix_a0_startup.py` | Not a permanent hang: ~2 min crash-loop on `/usr/bin/python3: Permission denied` (overlay/+x settle; bash was already +x so seed check skipped chmod), then ~1 min first-run deps (framework pins + spaCy `en-core-web-sm` via egress) before uvicorn. Entrypoint prefers `/opt/venv-a0/bin/python` + short wait/chmod; seed exec check includes python; health step surfaces `a0-init.log` lines. Unit: `tests/test_a0_startup_python.py`. Second open is fast. |
| **CUDA `.so.1` + `libggml-cuda.so.0` sonames (no Vulkan on NVIDIA)** | In tree; **must re-hotfix on clean v0.8.2** | Shipping v0.8.2 ISO can miss SONAME symlinks → CUDA binary fails → pick-gpus **Vulkan** on RTX (health `backend=vulkan`, process `llama-server-vulkan`). Fix: `stickllm-hotfix` `ensure_cuda_sonames` (always) + `docker-build-llama.sh` also links `libggml-cuda.so.0`. Push: `out/_hotfix_cuda_sonames_v082.py`. Verify: health `backend=cuda`. |

## Already in v0.8.2 — confirm on next clean flash

| Item | Notes |
|------|-------|
| **Experimental progress / installed / Set default** | CHANGELOG 0.8.2. Lab scripts `_hotfix_exp_progress_v082*.py`, `_hotfix_exp_installed_v082c.py`, `_hotfix_exp_set_default_v082.py` only if flash predates bake or verify fails. |
| **Unlock curl/tar fallback (+ bake `git`)** | `clone_or_update` in `stickllm-experimental-unlock`. |
| **Email Network fields; Minesweeper board-tile; A0 `/agent-zero/` + `setupBlocksAgent` + embed CSS** | CHANGELOG 0.8.2 “Prior hotfixes in bake” / 0.8.1. |
| **VL-7B catalog; 32K floor; download override; HF fuzzy; firmware-mediatek** | In 0.8.2 ship narrative. |

## Data plane (stick swap — not ISO bake)

See [HOTFIX-AFTER-STICK-SWAP.md](HOTFIX-AFTER-STICK-SWAP.md) § Data plane:

- **STICKLLM-DATA** claim/mount (survives reflash if kept).
- **STICKLLM-EXT** lab external models volume — format/label **outside** StickLLM; product only **Mount** under `/mnt/stickllm-host/` (never format host disks).
- **Seagate / host models + vault attach** after new stick boots.

## How to use vision (lab / user)

1. **Load a VL model with mmproj.** Models → pick Qwen2.5-VL-7B / Qwen3-VL-8B (or similar). If the **vision** pill is grey, tap it to download mmproj, then **Load**. Header chip should show `cuda · vision` (or backend · vision).
2. **Prefer StickLLM chat for images.** Paperclip / drag / paste into the message box (placeholder says “paste an image”). Send. The model must already be vision-loaded — text-only loads skip image bytes. Browser UI shrinks images client-side before send; StickDroid should send already-shrunk data-URLs (≤ ~180k chars).
3. **Agent Zero.** After a VL model is loaded, `stickllm-agent sync-model` sets preset `vision: true` from the active mmproj. Attach/paste images in the Agent Zero window or StickDroid — the stickllm_apps hook embeds image attachments into the VL call automatically. If A0 was open with an old `vision: false` preset, sync (or reload the model) so settings refresh.
4. **Quick check.** Health `connect.vision` true + a realistic (~50 KB) image `/api/chat` completion should answer about the image (not “no image was provided”). Tiny 1×1 always worked; the budget bug only hit real photos. Wrong mmproj pairing is fixed by the `find_mmproj` family match above.

## Out of scope here

- StickLink Method C / Always-On WIP on this worktree (separate track; not a post-0.8.2 vision hotfix).
- ISO cut / flash — only when explicitly requested.
