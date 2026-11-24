# Hotfix after stick swap — COMPLETE checklist

> **Historical (v0.8.2 → v0.8.3 era).** Most rows here are already in later shipping ISOs
> (through **v0.8.8**). Prefer [NEXT-0.8.9.md](NEXT-0.8.9.md) + [ISSUES.md](../ISSUES.md) for
> current open work. Keep this file for lab recovery when flashing an **old** restore ISO.

**This file is the durable list for that era.** After flashing a clean **pre-bake** stick from
that window, walk **§1 Master table** top-to-bottom. Do not improvise from memory.

Companion bake list (historical): [NEXT-0.8.3.md](NEXT-0.8.3.md)  
How to push: stage under `/tmp/stickllm-hotfix/<overlay path>` then
`sudo -n stickllm-hotfix [units…]` — [DEV-WORKFLOW.md](DEV-WORKFLOW.md).  
Lab drivers: gitignored `out/_hotfix_*.py` (recreate from this table if missing).

**Rules**

- Do **not** print SSH passwords (boot splash / F10 / health `connect.ssh_password`).
- Do **not** flash/overwrite a shipping ISO name ([RESTORE.md](RESTORE.md)).
- Prefer one authoritative edit of **this** file (merge sibling work; do not fork).
- Lab host for this desk: `192.168.72.50`. Password from **this stick’s** boot
  photo / F10 — never a stale `s60pw` from another stick.

---

## Decision tree (new stick)

```text
Flash StickLLM-v0.8.3.iso (hash 26ceba9f…) + full readback
  ├─ VERIFY MOST of User A 1–14 (vision/Terminal/UI) — usually baked
  ├─ MUST HOTFIX on clean v0.8.3 until v0.8.4:
  │     #1 CUDA sonames — BAKE REGRESSION: shipping v0.8.3 still boots
  │     Vulkan on RTX (soname links missing; pick-gpus had no ensure;
  │     stickllm-hotfix alone never runs at first boot)
  └─ DATA PLANE (§3): Mount Seagate/host → models + vault; Claim STICKLLM-DATA

Flash StickLLM-v0.8.2.iso (hash c678993c…) — older restore
  ├─ VERIFY BAKED-0.8.2 rows; MUST hotfix full §1 A table (incl. CUDA sonames)
  └─ DATA PLANE (§3)
```

**v0.8.3 CUDA soname bake regression (2026-11-22):** Item 15 was marked
“in tree” because `stickllm-hotfix ensure_cuda_sonames` + `docker-build-llama.sh
link_soname` existed — but the ISO still shipped `/opt/stickllm/lib` **without**
`.so.1` / `libggml-cuda.so.0` (llama rebuild skipped; skip path did not link),
and **nothing at boot** created them (`stickllm-pick-gpus` in the ISO had no
`ensure_cuda_sonames`). Fresh flash → `STICKLLM_BACKEND=vulkan` on 3090.
**Live fix:** `out/_hotfix_cuda_boot_path.py` (preferred) or
`_hotfix_cuda_sonames_v082.py`. **Next cut (v0.8.4) — DO NOT LEAVE OFF:**
see [NEXT-0.8.4.md](NEXT-0.8.4.md) **#1** — `ensure_cuda_sonames` in
`stickllm-pick-gpus` (already in tree) + bake gate that fails without it.
Do **not** overwrite `StickLLM-v0.8.3.iso`.

---

## §1 Master table — apply / verify every row

**Status column**

| Tag | Meaning |
|-----|---------|
| **MUST** | Live-only on clean **v0.8.2** until v0.8.3 ships — always push if verify fails |
| **BAKED-0.8.2** | In shipping ISO — verify; hotfix only if verify fails |
| **DATA** | Not ISO code — remount / claim / attach after swap |
| **STICKLINK** | Method C / Always-On lab — separate track; do not block desk recovery |
| **SUPERSEDED** | Older script; prefer the newer row listed in Notes |

### A. MUST — re-apply on clean v0.8.2

| # | Item | Script (`out/…`) | Verify (must pass) |
|---|------|------------------|--------------------|
| 1 | **CUDA `.so.1` + `libggml-cuda.so.0` sonames** (else Vulkan on NVIDIA) — **MUST on clean v0.8.2 and v0.8.3** until v0.8.4 | `_hotfix_cuda_sonames_v082.py` (+ push `stickllm-pick-gpus` with `ensure_cuda_sonames` for reboot survival) | `/api/health` → `backend=cuda`; `cat /run/stickllm/cuda.env` has `STICKLLM_BACKEND=cuda`; process `/opt/stickllm/bin/llama-server` (not `-vulkan`); `ls /opt/stickllm/lib/libllama-common.so.1 /opt/stickllm/lib/libggml-cuda.so.0`; `grep -c ensure_cuda_sonames /usr/local/bin/stickllm-pick-gpus` ≥ 1 (boot path) **and/or** hotfix ≥ 1 |
| 2 | **`find_mmproj` family match** | `_hotfix_mmproj_match.py` | `grep -n _mmproj_family_key /usr/local/bin/stickllm-control`; load Qwen3-VL-8B → matching mmproj (not VL-3B leftover); unit `tests/test_v053.py::test_c_find_mmproj_prefers_matching_family` |
| 3 | **Chat vision attach budget** | `_hotfix_vision_budget.py` | `grep IMAGE_TOKEN_ESTIMATE=1024 /usr/local/bin/stickllm-convert`; ~50 KB photo `/api/chat` describes image (not “no image”); `tests/test_attachments.py` |
| 4 | **A0 vision follows mmproj** | `_hotfix_a0_vision.py` then `_hotfix_a0_vision_flag.py` | `grep -n _model_vision /usr/local/lib/stickllm_agent.py`; after VL load: `stickllm-agent sync-model`; preset/plugin `vision: true` |
| 5 | **A0 phone/image attach hook** | same as #4 (writes `_20_stickllm_attach_images`) | `grep -n stickllm_attach_images /usr/local/lib/stickllm_agent.py`; upload photo in A0 → model describes it; `tests/test_agent_zero.py` |
| 6 | **A0 first-start crash-loop / health progress** | `_hotfix_a0_startup.py` | `grep -n a0_python /usr/local/bin/stickllm-agent-entrypoint`; Open Agent → Waiting shows real init lines; no multi-minute `python3: Permission denied` loop in docker logs |
| 7 | **Apps desk Terminal icon** | `_hotfix_terminal_icon.py` | Desk Terminal next to Files/Browser; `grep -n terminal_open /usr/local/bin/stickllm-control`; packages `xfce4-terminal`/`xterm` installed (**v0.8.2 live often lacks them — `apt-get install -y xfce4-terminal xterm` or Terminal icon returns `no_terminal`**) |
| 8 | **Terminal → StickLLM taskbar** | `_hotfix_terminal_taskbar.py` | Open Terminal → taskbar button; minimise/restore; `grep -n terminal_status /usr/local/bin/stickllm-control` |
| 9 | **XFCE Desktop Terminal launcher** | `_hotfix_terminal_icon.py` (same push) | `test -f /usr/local/share/stickllm/desktop/Terminal.desktop` and `~/Desktop/Terminal.desktop` |
| 10 | **SSH password Copy button** | `_hotfix_ssh_copy.py` | Devices / F10: **Copy** next to password; toast “Password copied” (do not print password) |
| 11 | **SSH password → Terminal paste** (`xclip` + Ctrl+Shift+V + Enter) | `_hotfix_terminal_paste.py` | **Paste into Terminal** works; `grep -n 'ctrl+shift+v' /usr/local/bin/stickllm-control`; `which xclip` |
| 12 | **Paste empty-clipboard fix + Terminal z-order** | `_hotfix_terminal_paste.py` (same) | At sudo prompt: paste succeeds (no “Sorry, try again”); click Settings/Agent → Terminal minimises; `grep -n _x11_clipboard_put /usr/local/bin/stickllm-control`; `grep -n 'wm.focus = (id)' /opt/stickllm/ui/desktop.js` + `yieldNative` |
| 13 | **`/etc/sudoers.d/stickllm-ssh`** (Test/Terminal boots password `ALL`) | `_hotfix_terminal_paste.py` / overlay `etc/sudoers.d/stickllm-ssh` | `test -f /etc/sudoers.d/stickllm-ssh`; `visudo -cf` OK |
| 14 | **Helpers NOPASSWD** (`stickllm-hotfix` / control / systemctl) | `_finish_stick_hotfixes.py` stages `zz-stickllm-helpers` | `sudo -n stickllm-hotfix -h` works; `test -f /etc/sudoers.d/zz-stickllm-helpers` (or equivalent helpers drop-in) |
| 15 | **About website → stickllm.com** | `_hotfix_about_domain.py` | About → Website `stickllm.com`; `grep stickllm.com /opt/stickllm/ui/index.html`; **no** `stickllm.org` in that row |
| 16 | **Experimental UI copy cleanup** | `_hotfix_exp_copy.py` | No “3 November 2026” / “require Debian 13” scare text; OS line “Detected OS major …”; `NOV3_CONTEXT` is opt-in-only wording |
| 17 | **Setup vault: USB HDD / other drive** | `_hotfix_setup_usb_storage.py` | `grep -n usb_unmounted /usr/local/bin/stickllm-control`; Setup → Storage lists USB Mount; Vault → **Choose a different drive**; `grep refreshWizardStorage /opt/stickllm/ui/app.js`; unit `tests/test_v083_setup_usb_storage.py` |
| 17b | **LAN browser desk open (A0 / Minesweeper / apps)** | `_hotfix_browser_open_apps.py` | Pair on `https://<stick>/` (F9); **single-click** wall Agent Zero + Minesweeper open in WinBox on **that** browser; `grep -n needsLanPair /opt/stickllm/ui/desktop.js`; unpaired click toasts pair (not blank 401 iframe); `index.html` cache `?v=v083browser` |

### B. BAKED-0.8.2 — verify; hotfix only if verify fails

| # | Item | Script if verify fails | Verify |
|---|------|------------------------|--------|
| 18 | **Experimental progress bar** | `_hotfix_exp_progress_v082.py` / `_hotfix_exp_progress_v082b.py` | Experimental download shows shared progress JSON/UI |
| 19 | **Experimental installed detection** | `_hotfix_exp_installed_v082c.py` | Status marks downloaded engines **Installed** |
| 20 | **Experimental Set default / Use** | `_hotfix_exp_set_default_v082.py` | Set default → NInfer/Strata on `:8080`; Use llama.cpp restores |
| 21 | **Unlock curl/tar fallback (no git)** | `_hotfix_exp_progress_v082.py` / unlock path | Unlock Cancel/Continue; clear JSON error if fetch fails |
| 22 | **Network email + vault Email/Password** | `_hotfix_email_vault_creds.py` (+ `_hotfix_email_outbound.py`, `_hotfix_email_a0_inode.py`) | Settings → Network: toggle shows fields; save to vault |
| 23 | **Minesweeper board-tile + skin + adapter** | `_hotfix_a0_minesweeper3.py` (prefer) / `_hotfix_a0_minesweeper*.py` | `test -f …/minesweeper/Minesweeper/client/board-tile.bundle.js`; `stickllm-adapter.js` has `window.stickllmApp` `describe`/`state`/`act`; A0 `app_state` / reveal-flag |
| 24 | **A0 `/agent-zero/` same-origin + `setupBlocksAgent`** | `_hotfix_a0_open.py` | Agent URL is `/agent-zero/`; `grep -n setupBlocksAgent /opt/stickllm/ui/app.js`; `curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1/agent-zero/` → 200 |
| 25 | **A0 embed input CSS** | gateway via `_hotfix_a0_open.py` / bake | `grep -n _EMBED_LAYOUT_CSS /usr/local/bin/stickllm-gateway`; Chat input visible in embed |
| 26 | **open_app → requesting browser client** (not kiosk) | `_hotfix_a0_open.py` / `_hotfix_a0_minesweeper3.py` (gateway + UI) | `grep -n stickllm_device /usr/local/bin/stickllm-gateway /opt/stickllm/ui/app.js`; `grep -n agent_lan /usr/local/bin/stickllm-gateway`; `app_not_open` 409 (no kiosk fallback); LAN A0 open_app opens Minesweeper on **that** browser |
| 27 | **VL-7B catalog (drop weak VL-3B)** | `_hotfix_vl7b_catalog.py` | Catalog / control has `qwen25-vl-7b-q4km`; no preferred `qwen25-vl-3b-q4km` |
| 28 | **32K floor** | `_hotfix_ctx32_floor.py` → `_hotfix_ctx32_activate.py` / `_hotfix_ctx32_finish.py` / `_hotfix_ctx32_planfix.py` | Active model `ctx_size` ≥ 32768 when policy allows; no false free-VRAM refuse |
| 29 | **Download override (mmproj soft gates)** | `_hotfix_download_override.py` | Soft-gate download path works when mmproj/gates blocked |
| 30 | **HF fuzzy search** | `_hotfix_hf_fuzzy_search.py` | Models search: typo `lnkling` → Inkling |
| 31 | **firmware-mediatek** | `_hotfix_firmware_mediatek.py` | Package/firmware present for lab Wi-Fi sticks that need it |
| 32 | **Load / download UI stuck “Loading”** | `_hotfix_load_download_ui.py` | Installed-after-download updates live; Loading clears |
| 33 | **mmproj unverified override + vision UX** | `_hotfix_mmproj_unverified.py` | Unverified mmproj can still attach when user overrides |
| 34 | **CUDA detect / register `.so`** | `_hotfix_cuda_detect.py` / `_hotfix_register_so.py` | CUDA backend selected on NVIDIA after detect; register preload OK |
| 35 | **Ethernet prefer / skip Wi-Fi** | `_hotfix_ethernet_prefer.py` / `_hotfix_ethernet_skip_wifi.py` | Network wizard prefers ethernet when cable present |
| 36 | **Delete-vault passcode focus** | `_hotfix_delete_vault_pass.py` | Delete-vault passcode field focusable |
| 37 | **No-vault re-probe after delete** | `_hotfix_novault_probe.py` | After vault delete, UI re-probes (no stale unlock) |
| 38 | **Experimental no-master / per-card Continue** | `_hotfix_exp_no_master.py` / `_hotfix_exp_v081.py` / `_hotfix_exp_and_prior.py` | Per-card Continue without master unlock gate |
| 39 | **MoE / TTFT ctx** | `_hotfix_ttft_moe.py` | MoE load path / TTFT sane on Inkling-class models |
| 40 | **Remove lab-only ctx32 force** | `_hotfix_remove_lab_ctx32.py` | Lab force path gone; product 32K refuse policy remains |

### C. DATA plane (every stick swap — not bake)

| # | Item | How | Verify |
|---|------|-----|--------|
| 41 | **Claim / keep `STICKLLM-DATA`** | Settings → Claim USB free space | `lsblk` shows label; `/mnt/stickllm-data` or stick data mount |
| 42 | **Mount host / Seagate / `STICKLLM-EXT`** | Storage → Mount (never format host disks) | `/mnt/stickllm-host/…` present; Find models sees GGUFs |
| 43 | **Vault attach / unlock** | `stickllm-vault attach …` or wizard; Unlock | `/api/health` vault `unlocked`; never Create over existing `stickllm-vault.img` |
| 43b | **Load a VL model** (else chat/A0 `vision: false`) | Models → Activate Qwen3-VL-8B (or VL-7B) from EXT/DATA + matching mmproj | `/api/health` `connect.vision=true`; llama cmdline has `--mmproj` family match; then `stickllm-agent sync-model` |

### D. STICKLINK / Method C (optional lab — separate track)

| # | Item | Script | Verify |
|---|------|--------|--------|
| 44 | Method C peer keepalive | `_hotfix_keepalive_peer.py` / `_hotfix_keepalive_v2.py` | Peer stays connected without false idle expiry |
| 45 | Method C remint peer | `_hotfix_remint_peer.py` | Remint path works via hotfix + vmtest oneshot |
| 46 | Zombie WSS / false-connected | `_hotfix_zombie_keepalive.py` | No zombie “connected” after WSS death |
| 47 | QR state machine | `_hotfix_qr_state_machine.py` | QR UI states match peer |
| 48 | Rate-limit UI / NL | `_hotfix_rate_limit_ui.py` / `_hotfix_ratelimit_nl.py` | Countdown + newline OK |
| 49 | StickLink server e2e helpers | `sticklink-server/lab-browser-e2e/_hotfix_*.py` | Lab e2e only — not desk kiosk |

### E. Orchestrators (run these, don’t skip the rows)

| Script | Role |
|--------|------|
| `out/_run_stick_swap_hotfixes.py` | Ordered MUST push (#1 CUDA + #4–17 + A0 open/startup); refreshes `s60pw` from boot-photo candidates |
| `out/_finish_stick_hotfixes.py` | Bulk stage overlay UI/control/convert/gateway + sudoers-ssh/helpers via `sudo -S` |
| `out/_fix_helpers_sudoers.py` | Repair `/etc/sudoers.d/zz-stickllm-helpers` so `sudo -n stickllm-hotfix` works |
| `out/_audit_hotfix_checklist.py` | Read-only marker dump on stick (redact passwords from any saved log) |
| `out/_verify_stick_swap_table.py` | Emit results markdown table for §5 |

---

## §2 Suggested push order (v0.8.2 → match live kiosk)

1. **CUDA sonames** (#1) if health `backend=vulkan` on NVIDIA — before vision/A0 load tests.  
2. Helpers/sudoers (#13–14) so later `sudo -n stickllm-hotfix` works.  
3. Experimental copy (#16).  
4. mmproj family (#2) → vision budget (#3) → A0 vision/attach (#4–5) → A0 startup (#6).  
5. Terminal icon (#7) → taskbar (#8–9) → SSH Copy (#10) → paste/z-order (#11–12).  
6. About (#15) → vault USB storage (#17).  
7. Verify BAKED rows (#18–40); re-push `_hotfix_a0_open.py` / `_hotfix_a0_minesweeper3.py` if open_app/Minesweeper client targeting fails (#23–26).  
8. Data plane (#41–43).  
9. Smoke: VL photo Chat + A0; Terminal icon + bar; Devices Copy → Paste into Terminal; `/agent-zero/` 200; LAN open_app Minesweeper on **requesting** browser; `/api/health` `backend=cuda`.

---

## §3 Data plane notes

### STICKLLM-DATA

- Claim USB free space → label **`STICKLLM-DATA`** + ~256 MB settings — [MODELS.md](MODELS.md).  
- Survives ISO reflash only if that partition is kept.

### STICKLLM-EXT (lab convention — no product string today)

1. Label external USB/HDD **outside** StickLLM.  
2. StickLLM **Mount** only under `/mnt/stickllm-host/<name>` — never format host disks.  
3. Point Models / Find models at `<mount>/models`.

### Seagate / host restore

- After boot: Storage → Mount Seagate → Find models / Activate.  
- Vault: `sudo stickllm-vault attach /mnt/stickllm-host/<mount>/…` — [VAULT.md](VAULT.md).

---

## §4 Out of scope

- StickLink Method C product ship (rows 44–49 are lab-only reminders).  
- Cutting/flashing a new ISO — only when explicitly requested; new name only
  (`v0.8.4` / `StickLLM-v0.8.4.iso`). Never overwrite shipping `v0.8.3`.  
- Do **not** resume unrelated Multitask agents (e.g. Wire A0 phone images).

---

## §5 After you finish a stick

Update a lab note (chat / store) with a copy of this results shape — keep secrets out:

```markdown
| Item | Applied | Verified working | Notes |
|------|---------|------------------|-------|
| CUDA sonames | yes/no | yes/no | … |
```

Next stick swap: start again at **§1 #1**. The list above is the whole list.
