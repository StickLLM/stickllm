# Hotfix after stick swap (kiosk recovery)

The lab kiosk often stays on an **older flashed image** while we fix bugs live via
`sudo -n stickllm-hotfix` / `out/_hotfix_*.py`. When you put in a **new stick**
(ship **v0.8.2** or later, then **v0.8.3** once cut), use this checklist so every
live-only fix is either **already in the ISO** or **re-pushed** before trusting
the desk.

**Companion bake list:** [NEXT-0.8.3.md](NEXT-0.8.3.md)  
**How to push:** stage under `/tmp/stickllm-hotfix/<overlay path>` then
`sudo -n stickllm-hotfix [units…]` — see [DEV-WORKFLOW.md](DEV-WORKFLOW.md) /
[CURSOR-HISTORY-agentzero.md](CURSOR-HISTORY-agentzero.md). Lab drivers live in
gitignored `out/_hotfix_*.py` (recreate from this table if missing).

Do **not** print SSH passwords. Do **not** flash/overwrite a shipping ISO name.

---

## Decision tree (new stick = v0.8.2 clean flash)

```text
Flash StickLLM-v0.8.2.iso (hash c678993c…) + full readback
  ├─ VERIFY ONLY (baked in 0.8.2): CUDA .so.1, Experimental Set default /
  │     progress / installed, unlock curl+git, email fields, Minesweeper
  │     board-tile, A0 /agent-zero/ + setupBlocksAgent + embed CSS, VL-7B
  │     catalog, 32K floor, download override, HF fuzzy, firmware-mediatek
  ├─ MUST HOTFIX until v0.8.3 ISO exists (live-only today):
  │     mmproj family match, vision attach budget, A0 vision+phone attach,
  │     Terminal desk + XFCE Desktop launcher, Experimental UI copy cleanup
  └─ DATA PLANE (not ISO code): Mount Seagate/host → models + vault attach;
        Claim / keep STICKLLM-DATA; optional STICKLLM-EXT external models volume
```

If the new stick is already a **v0.8.3** bake that includes the “Must bake”
rows in [NEXT-0.8.3.md](NEXT-0.8.3.md), skip those hotfixes — still run the
**verify** column once.

---

## Must re-apply on a clean v0.8.2 stick (live-only / Unreleased)

| Item | Why | Push (`stickllm-hotfix` / `out/_hotfix_*.py`) | Verify |
|------|-----|-----------------------------------------------|--------|
| **`find_mmproj` family match** | Crowded models dir picked wrong mmproj (e.g. VL-3B projector for Qwen3-VL-8B) | `out/_hotfix_mmproj_match.py` → `usr/local/bin/stickllm-control` | Load Qwen3-VL-8B; `STICKLLM_MMPROJ` / health shows matching family; unit `tests/test_v053.py::test_c_find_mmproj_prefers_matching_family` |
| **Chat vision attach budget** | Real JPEGs tokenized as text (~37k) → dropped under 60% budget → “no image” | `out/_hotfix_vision_budget.py` → `stickllm-convert`, `opt/stickllm/ui/app.js` | `grep IMAGE_TOKEN_ESTIMATE=1024`; ~50 KB photo `/api/chat` describes image; `tests/test_attachments.py` |
| **A0 vision follows mmproj** | A0 hardcoded `vision: false` while chat multimodal worked | `out/_hotfix_a0_vision.py` / `_hotfix_a0_vision_flag.py` → `usr/local/lib/stickllm_agent.py` | After VL load: `stickllm-agent sync-model`; preset/plugin `vision: true` |
| **A0 phone/image attach hook** | StickDroid uploads stayed filename-only; agent said it can’t see images | Same agent push (hook `_20_stickllm_attach_images` written on sync) | Upload photo in A0 → model describes it (lab: `39.jpg` → screwdriver); `tests/test_agent_zero.py` attach asserts |
| **Apps desk Terminal icon** | No desk Terminal next to Files/Browser | `out/_hotfix_terminal_icon.py` → `stickllm-control` (`terminal_open`), `ui/index.html`, `app.js`, `desktop.js`, `style.css`, `stickllm-hotfix` | Desk Terminal opens terminal (loopback UI); packages `xfce4-terminal`/`xterm` present or install |
| **XFCE Desktop Terminal launcher** | No trusted `~/Desktop/Terminal.desktop` | Same script → `usr/local/share/stickllm/desktop/Terminal.desktop`, `stickllm-kiosk`, `stickllm-xfce-session` | `~/Desktop/Terminal.desktop` trusted; opens `xfce4-terminal` |
| **Experimental UI copy cleanup** | Stale “Nov 3 2026” / Debian-13 scare copy on Experimental tab | `out/_hotfix_exp_copy.py` → `stickllm_experimental.py`, `stickllm-control`, `ui/index.html`, `ui/app.js` | No “3 November” / “require Debian 13” in UI or `nov3_context`; OS line says “Detected OS major …” |

---

## Already in v0.8.2 ISO — verify; hotfix only if verify fails

| Item | Why it was hotfixed live | Baked via | Verify (skip push if OK) |
|------|--------------------------|-----------|--------------------------|
| **CUDA / llama `.so.1` sonames** | Missing SONAME links → CUDA llama-server fail | `scripts/lib/docker-build-llama.sh` `link_soname`; CHANGELOG 0.8.2 “Prior hotfixes” | `systemctl is-active stickllm-llama`; journal has no missing `.so.1`; lab fallbacks `_hotfix_register_so.py` / `_hotfix_cuda_detect.py` |
| **Experimental progress bar** | Shared download JSON / UI bar for Strata+NInfer | 0.8.2 bake; lab `_hotfix_exp_progress_v082.py` / `…_v082b.py` | Experimental download shows shared progress |
| **Experimental installed detection** | Disk scan → Installed + Re-download | 0.8.2; lab `_hotfix_exp_installed_v082c.py` | Status marks downloaded engines Installed |
| **Experimental Set default / Use** | Switch chat+A0 onto NInfer/Strata on `:8080` | 0.8.2; lab `_hotfix_exp_set_default_v082.py` | Confirm Set default; `/health` / active-engine JSON; Use llama.cpp restores |
| **Unlock curl/tar fallback (no git)** | Live image may lack `git`; clone must not hard-fail | 0.8.2 (`clone_or_update` + bake `git`); lab via exp progress/unlock push | Unlock Cancel/Continue; clear JSON error if fetch fails |
| **Network email + vault Email/Password** | Toggle + vault fields for A0 mail | 0.8.2 prior bake; `_hotfix_email_vault_creds.py` (+ outbound/inode) | Settings → Network: toggle shows fields; save to vault |
| **Minesweeper board-tile + skin** | Board bundle + A0 `app_act` adapter | 0.8.2 prior; `_hotfix_a0_minesweeper*.py` / `_hotfix_a0_open.py` | `board-tile.bundle.js` loads; A0 minesweeper `app_state` / `new_game` |
| **A0 embed input CSS** | Plugin skeleton pushed `#chat-input` off iframe | 0.8.2 prior; `stickllm-gateway` `_EMBED_LAYOUT_CSS` | Kiosk/LAN Chat: input visible; `tests/test_v064_agent_embed.py` |
| **`setupBlocksAgent`** | Open A0 was silent no-op on LAN until local wizard | 0.8.1+; `_hotfix_a0_open.py` | Vault open + pair: Open Agent Zero works without local wizard markers |
| **`/agent-zero/` LAN same-origin** | Stop minting `:5443` / raw `:5099` for iframe | 0.8.1+; same A0 open hotfixes | Agent URL is `/agent-zero/`; CSRF probe before embed |
| **VL-7B catalog (drop weak VL-3B)** | Pin quality vision @ ≥12 GB | 0.8.2; `_hotfix_vl7b_catalog.py` | Catalog has `qwen25-vl-7b-q4km`; no `qwen25-vl-3b-q4km` |
| **32K floor / download override / HF fuzzy / mediatek firmware** | Load/policy/Wi‑Fi polish | 0.8.1–0.8.2 prior | Spot-check if stick behaves oddly; scripts under `out/_hotfix_ctx32_*`, `_hotfix_download_override.py`, `_hotfix_hf_fuzzy_search.py`, `_hotfix_firmware_mediatek.py` |

---

## Data plane after swap (not baked into ISO code)

These survive or fail independently of which ISO you flash. Record them so the
new stick sees the same models/vault.

### STICKLLM-DATA (boot stick free space)

- First-boot / Settings: **Claim USB free space** → label **`STICKLLM-DATA`**
  (ext4) + ~256 MB settings slot — [MODELS.md](MODELS.md).
- Holds `models/`, optional vault pointer `stickllm-vault-location.json`, apps.
- **Survives ISO reflash** only if you keep that partition (do not wipe the whole
  stick layout when reclaiming). Product never formats host disks.

### STICKLLM-EXT (lab external models volume)

There is **no `STICKLLM-EXT` string in product code** today. Lab convention:

1. Format/label an **external** USB/HDD **outside** StickLLM (Windows Disk
   Management / Linux tools) if you want a durable models disk — e.g. volume
   name **`STICKLLM-EXT`** so it is obvious next to `STICKLLM-DATA`.
2. On the stick: Storage → **Mount** only (read-write under
   `/mnt/stickllm-host/<name>`). StickLLM **never partitions or formats** that
   disk (`stickllm-vault` / control Mount path).
3. Point Models / Find models at `<mount>/models` (or your usual layout).
4. After stick swap: plug in → Mount again → Find models / Activate. Do not
   expect the new ISO to auto-format EXT.

### Models on Seagate (lab host) restore path

- Lab **Seagate Backup** (`NA8TPCBG` / similar) is a **host** disk — flash
  wrappers refuse to write it ([CURSOR-HISTORY-agentzero.md](CURSOR-HISTORY-agentzero.md)).
- After new stick boots: Settings → Storage → ensure Seagate appears (list-disks
  surfaces disks even when not yet mountable) → **Mount** →
  `/mnt/stickllm-host/…`.
- **Find models** / Load from that mount. Vault blob on SSD/Seagate:
  `sudo stickllm-vault attach /mnt/stickllm-host/<mount>/…` (never Create over
  an existing `stickllm-vault.img`) — [VAULT.md](VAULT.md).
- If Claim kept `STICKLLM-DATA`, prefer restoring via
  `stickllm-vault-location.json` pointer then Unlock.

---

## Suggested push order (v0.8.2 → match live kiosk)

1. Experimental copy (`_hotfix_exp_copy.py`) if UI still shows Nov-3 / Debian scare text.  
2. `stickllm-control` mmproj family (`_hotfix_mmproj_match.py`).  
3. Vision budget (`_hotfix_vision_budget.py`) + UI restart.  
4. `stickllm_agent.py` vision + attach (`_hotfix_a0_vision*.py`) + `stickllm-agent sync-model`.  
5. Terminal desk + Desktop launcher (`_hotfix_terminal_icon.py`); install
   `xfce4-terminal`/`xterm` if packages missing on old image.  
6. Mount Seagate/EXT → Find models → vault attach/unlock.  
7. Smoke: VL photo in Chat + A0; Experimental tab; Terminal icon; `/agent-zero/`
   on LAN.

If the outgoing kiosk was **older than 0.8.2**, also run the “Already in
v0.8.2” verify column — or re-push the matching `_hotfix_exp_*` /
`_hotfix_a0_open` / email / minesweeper scripts from the table above.

---

## Out of scope here

- StickLink Method C / Always-On WIP (separate track).  
- Cutting/flashing `v0.8.3` — only when explicitly requested; new name only
  ([RESTORE.md](RESTORE.md) N-2 rules).
