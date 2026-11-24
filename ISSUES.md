# StickLLM Issues Log

Lightweight product/bug log (same spirit as [FEATURES.md](FEATURES.md)). Not a GitHub Issues mirror.

**How to add an entry**
1. Pick the next `ISS-NNN` ID.
2. Put new open items at the top of **Open**.
3. Fill: ID, date, mode (Local / Term / Server / all), status, summary, notes/repro.
4. When fixed, move to **Closed** (or set status Closed) with a one-line resolution.

---

## Open

**Source of truth for next bake:** [docs/NEXT-0.8.9.md](docs/NEXT-0.8.9.md).
ISS-065…073 **shipped in v0.8.8 ISO**. Older shipped ISS ids are under **Closed** below.

### ISS-081 — Experimental: finish Strata (NInfer first; Strata next)
| | |
|---|---|
| **ID** | ISS-081 |
| **Date** | 2026-11-24 |
| **Mode** | Experimental / Models |
| **Severity** | MED (product completeness; not blocking v0.8.9 must-bake unless pulled) |
| **Status** | Open — agreed order: **NInfer first** (largely done through v0.8.8), **Strata next**, Maya (ISS-080) later |
| **Summary** | Experimental **Strata** can download + Set default on `:8080` (since v0.8.2), but **Models / Activate / catalog parity** still lags NInfer. Agreed: keep focusing polish on NInfer; then **configure Strata** the same way (compatible models list, download/Load path, honest copy, A0 on `:8080`). |
| **Already wired** | Engine download helper `strata`; Set default / Use llama.cpp; AppImage extract + CUDA pack notes in [DEBIAN13-EXPERIMENTAL.md](docs/DEBIAN13-EXPERIMENTAL.md). |
| **Still to do** | Strata-scoped Models catalog + filters; download/Load (or Activate) for Strata weights; queue/status parity with NInfer; lab confirm on 3090; docs walkthrough like [NINFER.md](docs/NINFER.md). Carry-forward from ISS-041 (“Strata same pattern later”) and ISS-044/045 notes. |
| **Not this ISS** | Maya + Inkling (ISS-080); sfnx 3× V100. |


### ISS-080 — Experimental: Project Maya + Inkling-2-Mini on RTX 3090 (~125 plain / ~200 with DSpark)
| | |
|---|---|
| **ID** | ISS-080 |
| **Date** | 2026-11-24 |
| **Mode** | Experimental / Models / RTX 3090 |
| **Severity** | LOW (future Experimental offer; not blocking v0.8.9) |
| **Status** | Open — future requirement; no bake commitment yet |
| **Summary** | Future **Settings → Experimental** offer for **`maya-ik2`** + **Inkling 2 Mini** on StickLLM’s lab **RTX 3090** (24 GB). Public measurements: **~125–128 tok/s** plain decode (vs ~57 llama.cpp); **~182–212 tok/s** on code/edits with **DSpark** through HTTP — the “~200 tok/s” story. Prefill ~2.5–2.7k tok/s; full experts in VRAM (Unsloth `UD-Q4_K_XL` ~17.6 GB + FP8 KV; up to ~262K–344K ctx). OpenAI/Anthropic-compatible `/v1`. |
| **Primary reference** | **[alesha-pro/maya-inkling-mini](https://github.com/alesha-pro/maya-inkling-mini)** — Inkling 2 Mini on one RTX 3090 guide, benches, quick start. Upstream engine product: [mw00/project-maya](https://github.com/mw00/project-maya) (`maya-ik2`, `./maya.sh --setup --model inkling-2-mini`). Weights: Unsloth `Inkling-2-Mini-GGUF` / `Inkling-2-Mini-UD-Q4_K_XL`. |
| **Not the same as sfnx** | [johnfink8/sfnx](https://github.com/johnfink8/sfnx) is a **different** engine: **3× V100** layer-split for **Qwen3.8-Flash-Next** (~382 tok/s code-edit). Do **not** treat sfnx as the 3090+Inkling path. Optional later Experimental curiosity only. |
| **Related engines (context)** | StickLLM already ships **NInfer** Experimental; NInfer-3090 also serves Inkling-2-Mini on 3090 (~104 tok/s plain per HF card) — slower than Maya’s published 3090 numbers. vLLM Inkling Ampere path ~100 / ~177 with DSpark (TP=2). |
| **Fit** | Same Experimental pattern as NInfer / Strata: Cancel/Continue, download, Set default on `:8080` when mature; Models Activate for Inkling; no NVIDIA blobs in StickLLM git; no auto-install. Lab-verify tok/s + OpenAI compat on StickLLM Debian 13 / CUDA bake before UI row. |
| **Order** | After Strata Models parity (**ISS-081**). Keep NInfer as general MoE; Maya as optional **Inkling-fast** — do not replace NInfer. |
| **Out of scope for now** | Must-bake for v0.8.9; default engine; shipping Maya binaries or weights inside the ISO without opt-in. |


### ISS-079 — Phone web client (stickllm.com/app) as StickDroid APK alternative
| | |
|---|---|
| **ID** | ISS-079 |
| **Date** | 2026-11-24 |
| **Mode** | StickLink / Mobile / Web |
| **Severity** | MED (product roadmap; not blocking v0.8.9 must-bake) |
| **Status** | Open — roadmap; lab WIP has connection / timeout issues |
| **Summary** | Prefer a **browser web app** that can eventually replace the StickDroid APK. Staging/live entry today: https://stickllm.com/app/ — scans StickLink QR, then opens a phone website after connect. |
| **Current state** | Early development (lab 2026-11-23 area): QR → connect → launch site works in outline; **connection drops / timeouts** still open. Not a shipping phone client yet. |
| **Goal** | Reliable Always-On session (pair once, resume, Chat / Work / A0 from ISS-078) without requiring Play/sideload APK. APK may remain a fallback until the web path is solid. |
| **Notes** | StickLink Worker / signalling stays closed source. Public stickllm.com/app is the client shell only. Related: ISS-036 (WSS resume), ISS-077 (multi-device). |


### ISS-078 — Phone modes: Chat / Work / A0 (restore StickLLM Chat for simple)
| | |
|---|---|
| **ID** | ISS-078 |
| **Date** | 2026-11-24 |
| **Mode** | StickDroid / web client / StickLink |
| **Severity** | MED (product roadmap; not blocking v0.8.9 must-bake) |
| **Status** | Open — design agreed; implement on phone clients post-0.8.9 unless pulled forward |
| **Summary** | Today Android “Chat” and “A0” are **both Agent Zero** (Chat only hides complexity). Product: three modes like ChatGPT simple vs agentic. |
| **Modes** | **Chat** = old StickLLM Chat UI (`ui/#app`, `/api/chat`) — simple Q&A, optional Web lookup, no A0 monologue. **Work** = rename today’s simplified A0 “Chat” (agent tasks, chrome stripped). **A0** = full Agent Zero UI. |
| **Handoff (agreed)** | Chat must be able to **hand off to Agent Zero** when needed. Default UX: **explicit** — user switches to Work / A0, or uses a “send to agent” / Agent Zero control (ChatGPT-style escalate). Stick already has this in `#app`: Agent Zero toggle → `/api/agent/ask` + poll, inline steps, link to full A0 window, clipboard fallback. Soft “switch to Work?” suggestion from the Chat model is OK. **Silent auto-escalate** mid-Chat without a user affordance is **later / optional** (needs clear rules so simple Q&A never always jumps to A0). |
| **Why** | Simple asks (e.g. price lookup with Web) should not pay full A0 planning tax; complex multi-step work stays in Work/A0, reachable from Chat without starting over. Desk still A0-only until we choose to re-host `#app` there. |
| **Code already on stick** | Chat UI + `/api/chat` never deleted — only desk WinBox mount retired (~0.6.5). Phone / web client must route Chat → `/api/chat`, Work/A0 → Agent Zero, and preserve Chat→A0 handoff (`/api/agent/ask` path or equivalent StickLink mux). |
| **Related** | ISS-079 (web app may replace APK); ISS-077 (multi-device). |


### ISS-077 — Multi-device pairing: up to 8 clients on one stick (shared vault first)
| | |
|---|---|
| **ID** | ISS-077 |
| **Date** | 2026-11-24 |
| **Mode** | LAN / StickLink / Devices / all |
| **Severity** | MED (product roadmap; not blocking v0.8.9 must-bake) |
| **Status** | Open — design + implement after v0.8.9 unless pulled forward |
| **Summary** | Today StickLLM effectively supports **one** paired device at a time. Product need: **up to 8** devices paired to the **same stick** so a phone, LAN browser, AIKVM, speaker/mic, etc. can all stay paired and talk (same LAN and/or via StickLink). |
| **Phase 1 (agreed first step)** | Multiple concurrent paired sessions → **one stick / one vault** (shared session mode + shared models). Pair + resume for each device without kicking the others. Cap **8**. Device list / revoke in Settings → Devices. |
| **Phase 2 (open design)** | Admin vs other users; shared vault vs per-user vaults; who can unlock, change models, flash, or revoke peers. Do **not** block Phase 1 on Phase 2. |
| **Notes** | Old FEATURES P2 “Multi-user server, separate vault per client” was only the Phase 2 shape. Capture lives in [FEATURES.md](FEATURES.md) Client and networking. StickLink Always-On / Method C and LAN pair both need a concurrent-session story. |


### ISS-076 — Design: StickLLM + Agent Zero must work when vault is locked (ephemeral)
| | |
|---|---|
| **ID** | ISS-076 |
| **Date** | 2026-11-23 |
| **Mode** | Local / Agent Zero / StickLink / all |
| **Severity** | HIGH (product design; hard-gates A0 + dockerd on vault mount) |
| **Status** | Open — bake in v0.8.9 |
| **Summary** | **Agreed product rule:** StickLLM and Agent Zero must work when the vault is locked. Vault lock only means no durable chat/secrets persistence (ephemeral). Unlock enables save to vault / HF in settings / durable A0 chats — **not** a hard gate that blocks A0 or core StickLLM. |
| **Docs vs code** | Session mode already documents ephemeral A0 chats on `/run/stickllm/a0-chats` (tmpfs). Older Lock / ARCHITECTURE text said A0 stops until vault mounts — that hard-gate reading is **superseded** by this rule (see [docs/VAULT.md](docs/VAULT.md)). Tree still implements the old gate. |
| **Tree blocks today (Y)** | (1) `stickllm_agent.docker_may_start` = vault mounted only (`Vault locked => docker must not start`). (2) `stickllm-agent` `ensure_dockerd` / `cmd_run_container` / `cmd_gate` → `refuse_locked` / state `locked`. (3) systemd `ConditionPathIsMountPoint=/var/lib/stickllm/vault` on `stickllm-agent.service` (+ install unit). (4) `status_document`: `state=locked`, message “Unlock vault to use Agent”; `running` requires `vault_open`. (5) UI: `ensureAgentZeroStarted` skips start when `!vault_unlocked`; Agent link detail “Unlock vault on this page”. |
| **Fix** | Remove vault-mount hard gate for A0/dockerd/core StickLLM. Locked → ephemeral A0 (tmpfs chats; no vault memory/secrets writes; no HF save to settings). Unlocked → durable vault store / HF in settings / durable A0 chats. Keep intentional Lock teardown of vault-backed add-ons, but allow (re)start A0 in ephemeral mode after lock without requiring unlock. Update ARCHITECTURE “skipped until vault mounted” accordingly. |
| **Not this ISS** | (a) Ephemeral A0 path itself — already partially in tree via session mode / `a0-chats-dir`. (b) Dual-USB settings discovery — **ISS-074**. (c) Corrupt USB docker graph — **ISS-075**. |


### ISS-075 — Corrupt A0 docker graph on USB DATA: `/bin/bash` missing → 503
| | |
|---|---|
| **ID** | ISS-075 |
| **Date** | 2026-11-23 |
| **Mode** | Local / Agent Zero / StickLink |
| **Severity** | HIGH (dockerd up; container never starts; StickLink 503) |
| **Status** | Open — bake in v0.8.9 |
| **Summary** | On a dual-USB lab stick (boot ISO + second-slot `STICKLLM-DATA`), `stickllm-dockerd` and image tag `stickllm/agent-zero:v2.15` look present, but `docker run … /bin/bash` fails with `stat /bin/bash: no such file or directory`. `stickllm-agent` restart-loops; gateway `/agent-zero/` returns `agent_not_running`. System `docker.service` masked is normal — StickLLM uses `stickllm-dockerd` + `/run/stickllm/agent-docker.sock`. |
| **Root cause (lab)** | Writable docker data-root at `/mnt/stickllm-data/stickllm-docker` held a broken overlay2 graph (corrupt/incomplete layer diffs or lost bind mounts / exec bits from prior USB use). `image-ready` / `image_present` stayed true so install was skipped; runtime only failed at runc. |
| **Fix** | (1) Detect broken graph (smoke `/bin/bash` or layer exec check on the **active** data-root, not only seed). (2) Auto-reseed from `/opt/stickllm/docker` via `ensure-seeded` / materialize when smoke fails — do not trust a tagged image that cannot exec. (3) Surface honest UI: “Agent image on DATA is damaged — repairing…” instead of endless starting. (4) Dual-USB: reclaiming old DATA must re-verify A0 graph, not assume old `stickllm-docker` is healthy. |
| **Lab (2026-11-23)** | v0.8.8 Lexar boot + old DATA @ 192.168.72.50. Moved corrupt `stickllm-docker` aside → `ensure-seeded` from `/opt/stickllm/docker` → bash smoke OK → A0 **running**, `/agent-zero/` **HTTP 200**. Product auto-detect/reseed still → bake v0.8.9. Related: ISS-074. |


### ISS-074 — Dual-USB: vault unlocks on second stick; A0 stuck `settings_missing` / `agent_not_running`
| | |
|---|---|
| **ID** | ISS-074 |
| **Date** | 2026-11-23 |
| **Mode** | Local / StickLink / Agent Zero |
| **Severity** | HIGH (UI looks unlocked; StickLink pairs then 503) |
| **Status** | Open — bake in v0.8.9 |
| **Summary** | Boot from a **new** StickLLM USB (iso only) with the **old** vault/DATA USB in a second slot: `STICKLLM-DATA` mounts from the second stick, vault unlock succeeds, Terminal/session UI looks ready, StickLink pairs (`noise ok`, `agent_ready`) then `A0 ui/index HTTP 503 agent_not_running`. Control says `vault_unlocked: true` but `state: settings_missing` — “Unlock the USB settings partition to use Agent”. |
| **Root cause** | `stickllm-usb-settings find_settings_part` only accepts `STICKLLM-SETTINGS` on the **boot** disk. Lab: boot=`sda` (no DATA/settings), DATA+LUKS settings on `sdb3`/`sdb4`. Labeled `sdb4` is rejected (`pk != boot_disk`) → status `usb_settings: absent`. Vault unlock’s `sync_usb_settings` therefore never opens settings even though the passcode was just accepted. Stale `stickllm-settings-part.json` can still point at `/dev/sda4` (missing). Agent loops “USB settings partition is not mounted” → `start-limit-hit`. `vault.key` alone does **not** open settings LUKS (needs vault passcode / matching keyslot). |
| **Fix** | (1) When mounted `STICKLLM-DATA` is off-boot, still discover/open `STICKLLM-SETTINGS` on that same DATA disk (or create settings on boot free space — do not exit early after mounting foreign DATA). (2) On vault unlock, if settings open fails as “absent” while a labeled settings LUKS exists on the DATA disk, open that partition with the same passcode and refresh the pointer. (3) UI: vault unlocked + `settings_missing` must not read as “A0 ready” (honest copy / gate). (4) Docs: preferred boot+DATA+settings on one stick; dual-USB reclaim is supported only if settings can open from the DATA stick. |
| **Lab (2026-11-23)** | v0.8.8 Lexar boot + old DATA stick @ 192.168.72.50. `vault.key` alone cannot open settings; vault passcode opens `sdb4` → real `/mnt/stickllm-settings` (HF token present). Product still boot-disk-only for `find_settings_part` → bake v0.8.9. Stacked with ISS-075 corrupt A0 graph; after manual settings open + reseed, A0 **running**. |


### ISS-036 — Peer reconnect still requires a WebRTC DataChannel; durable `?rt=` WSS resume deadlocks
| | |
|---|---|
| **ID** | ISS-036 |
| **Date** | 2026-11-21 |
| **Mode** | StickLink Always-On (stick peer + StickDroid) |
| **Severity** | HIGH (phone can sit on *Reconnecting* with a healthy stick) |
| **Status** | Open — needs the phone online to design and test against |
| **Summary** | `run_one_session` runs pair confirm, `agent_ready` and `sess.bind` over the DataChannel, and only afterwards sets `sess_bound` / `use_wss`. A phone that resumes the documented Always-On way (WSS `?rt=` + `sess.resume`, no WebRTC) arrives as `sess.peer join`, after which the peer waits 120s for a `pmsg need-offer` that never comes and fails with `no need-offer from phone`. ARCHITECTURE-ALWAYS-ON-SESSION calls WSS primary and WebRTC "never required"; the peer has it backwards. |
| **Notes** | Observed 2026-11-21 03:19 UTC: a client joined the resume mailbox within 1s of `resume.put`, then sent nothing for 120s. The build now logs `peer join <conn> via=peer\|sess.peer` plus a warning on `sess.peer`, so the next occurrence is unambiguous. Fix direction: when the joiner is `sess.peer`, run the Noise responder over `sess.frame` (the `complete_wss_handshake` machinery already exists) and skip offer/answer entirely. |



### ISS-034 — Method C lab automation: repeated Send after response timed out
| | |
|---|---|
| **ID** | ISS-034 |
| **Date** | 2026-11-08 |
| **Mode** | StickLink Method C / lab browser E2E |
| **Severity** | MED (automation / UX flake; operator LTE chats succeeded) |
| **Status** | Open — do not block v0.7.2 TEST bake |
| **Summary** | In `_e2e_lte_acceptance.py`, after msg1 (Send) and msg2 (Enter + search) succeeded, a third Send (`AGAIN_OK`) did not observe the reply within timeout. Agent status often still showed not-idle (`waiting=false`) after answers appeared. |
| **Notes** | Real iPhone LTE acceptance still passed with multiple chat exchanges. Track as open; do not “fix” by redesigning Method C in this cycle. |



### ISS-033 — LAN / desktop Agent Zero pairing broken after StickLink phone lab
| | |
|---|---|
| **ID** | ISS-033 |
| **Date** | 2026-11-08 |
| **Mode** | Local / LAN / Agent Zero |
| **Severity** | HIGH (desktop Agent Zero via original pairing) |
| **Status** | Open — **re-verify**; was broken in earlier lab, operator reports **legacy LAN pair PASS** on v0.7.2 TEST ISO (AMD, 2026-11-08) |
| **Summary** | After StickLink phone-join lab + pairing UI for StickLink QR, desktop Agent Zero through the original LAN pairing path was reported broken. Phone StickLink Method C (lab-assisted) works. |
| **Notes** | Architect: defer dedicated fix work in Method C cycle. 2026-11-08 AMD TEST flash: operator says legacy method paired — do not close until desktop Agent Zero use after pair is confirmed; do not assume still broken either. |



**Security is parked** (2026-10-16). Do not implement NINO, firewalls, the client-stick lockdown, zero-trust remote access, pairing/TLS redesign, or signed updates until the working product is settled. See [FEATURES.md](FEATURES.md).

### ISS-023 — Complete offline / NINO network lockdown (“nothing in, nothing out”)
| | |
|---|---|
| **ID** | ISS-023 |
| **Mode** | Local / Server / Client stick (all) |
| **Severity** | PRODUCT (P1 security posture) |
| **Status** | Parked — design only; do not implement until the product architecture is settled |
| **Summary** | True air-gap mode: when the user wants it, **nothing in, nothing out** at the OS/network layer — not merely chat-level Web lookup off. Today the UI **Web** pill only gates chat live lookup; Terminal, HF downloads, and other processes still reach the internet when the NIC is up. Settings → Network **Offline mode** is “Coming soon” / not wired (`ui/index.html` `#offline`). |
| **Notes** | **Goal:** NINO (nothing in, nothing out) air-gap posture the user can enable consciously. **Local / Server on same machine:** a “disable network” control that kills the NIC and/or firewalls all ingress/egress (simpler path). **Remote client stick:** still must talk to the StickLLM server over the **secure tunnel** only; allowlist that tunnel (paired server) and block all other ingress/egress. **Do not confuse with Web pill** — Web off ≠ OS offline. **HF / catalog downloads, updates, Tor, AP setup, etc. must be blocked or refused** while NINO is on. Open design questions: iptables vs nftables vs NetworkManager disconnect; WireGuard/SSH tunnel allowlist shape; LAN-pair-only vs internet-reachable server; how client stick discovers/keeps the tunnel without opening general egress; persistence across reboot; UX copy that distinguishes Web / Offline / NINO; interaction with Term SSH and BMC (out of StickLLM control). Track in FEATURES + THREAT-MODEL; implement later — **docs/issue only for this entry**. |



### ISS-022 — Companion apps catalog (USB DATA / vault)
| | |
|---|---|
| **ID** | ISS-022 |
| **Mode** | all / product |
| **Severity** | PRODUCT (P2 plan) |
| **Status** | Open — first-pass catalog only; **not shipping**; list may change |
| **Summary** | Potential companion apps (docs, mail, calendar, notes, tasks, search, chat, creative tools, agent operator) for humans via browser/UI and agents via each app’s API/tool layer. Install target: StickLLM USB DATA and/or encrypted SSD vault. Catalog: [docs/APPS.md](docs/APPS.md). |
| **Notes** | Chat voice is decided and baked into the **v0.4.2** ISO: whisper.cpp tiny.en and KittenTTS mini 0.8 (not Piper, not Kitten TTS 2), resident `whisper-server`, Voice on/off, streaming speech, stop button, 80-token spoken replies, hidden brief prompt, thinking text skipped while Voice is on, and 1 second of silence auto-sends after real speech. Weights are an image-build pin (`overlay/usr/local/lib/stickllm-speech.pin`), not downloaded at runtime, and not stored in the vault. Wake word is still later. n8n is fair-code (not OSI); Node-RED (Apache) is the OSI-friendly alternative under consideration. The companion-apps catalog is still not shipping. Do **not** bake or ship those catalog apps in v0.3.8. |



### ISS-021 — Next focus: build HF download/search + shared load filters + Advanced
| | |
|---|---|
| **ID** | ISS-021 |
| **Mode** | Local / Term / Server (Models UI) |
| **Severity** | PRODUCT (P0 next focus after v0.3.8) |
| **Status** | Open — partial in v0.3.9. Search, queue, hash check, and fit labels ship. Remaining: shared filters on installed models, and Advanced knobs that are not applied |
| **Summary** | Hugging Face search and the download queue exist. **Still to finish:** the same filters (**Verified** / known-hash, **Fits in VRAM**, **Untrusted**, quant, licence, abliterated) on **installed models** when choosing what to **load**. Wire **Advanced** controls that are on screen but not sent to llama (temperature, top-p, top-k, repeat penalty, max reply tokens, KV cache type). The backend segment stays disabled on purpose until a manual override is real (`ui/app.js` `#backendSeg`, preset toast “sampling knobs greyed”). |
| **Notes** | Pairs with ISS-020 (slim ISO shipped in v0.3.9). Catalog trust: `config/models/catalog.toml`. Context size already moves from the preset buttons and the context slider. Sampling and KV are stored in the page only. |



### ISS-012 — stickllm-kiosk usermod + world-writable /run/stickllm
| | |
|---|---|
| **ID** | ISS-012 |
| **Mode** | Local |
| **Severity** | MEDIUM |
| **Status** | Open (deferred in v0.3 — avoid breaking Local) |
| **Summary** | `stickllm-kiosk` runs **usermod** at runtime and does `chmod 777 /run/stickllm` plus **666** on logs; pair files live there. |



### ISS-013 — Chromium launched with --no-sandbox
| | |
|---|---|
| **ID** | ISS-013 |
| **Mode** | Local |
| **Severity** | MEDIUM |
| **Status** | Open (deferred in v0.3 — avoid breaking Local) |
| **Summary** | Chromium is launched with `--no-sandbox`. |



### ISS-014 — Hardcoded DRM/NVIDIA/threads/model/runtime/serial paths
| | |
|---|---|
| **ID** | ISS-014 |
| **Severity** | LOW |
| **Status** | Open (partial: threads/CPU in v0.3; DRM auto-pick deferred) |
| **Summary** | Hardcoded `/dev/dri/card0`, device indices, runtime paths. |



### ISS-015 — Build hook || true, chmod gaps, services, MOTD, hosts
| | |
|---|---|
| **ID** | ISS-015 |
| **Severity** | LOW |
| **Status** | Open (partial in v0.3 hook; fail-hard cleanup deferred) |
| **Summary** | Hook soft-fails; MOTD/hosts/chmod completeness. |



### ISS-017 — Delete patch-iso scripts and weston/cog/pixman fallbacks
| | |
|---|---|
| **ID** | ISS-017 |
| **Mode** | Local |
| **Severity** | CLEANUP |
| **Status** | Open (deferred until ISS-010 HW-proven) |
| **Summary** | Delete patch-iso / weston/cog/pixman fallbacks after kiosk reproducibility is solid. |

---



## Closed (v0.8.6)

### ISS-043 — A0 “Automatic chat naming failed” on NInfer (empty content / thinking)
| | |
|---|---|
| **ID** | ISS-043 |
| **Date** | 2026-11-23 |
| **Mode** | Agent Zero / NInfer |
| **Severity** | MED (chat works; naming toast every turn) |
| **Status** | Closed — **shipped in v0.8.6** |
| **Summary** | With NInfer `qwen3.8-27b`, utility/chat-naming calls return empty `content` and fill `reasoning_content` (thinking). A0 only reads `content` → “Automatic chat naming failed (utility model busy or unreachable).” StickLLM already set LiteLLM `extra_body.chat_template_kwargs.enable_thinking=false` for Qwen3.5; **NInfer ignores `extra_body`** and needs top-level `enable_thinking: false` / `chat_template_kwargs`. Also sync util/chat model id to `/v1/models` id (`qwen3.8-27b`), not a leftover GGUF name. |
| **Fix** | `_util_model_kwargs` + `presets.yaml` pass top-level thinking-off as well as `extra_body`; sync-model after NInfer Set default. |
| **Resolution** | Shipped in v0.8.6 ISO.


### ISS-042 — NInfer Set default never serves: STICKLLM_ACTIVE_ENGINE env path collision
| | |
|---|---|
| **ID** | ISS-042 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / NInfer |
| **Severity** | HIGH (Set default appears to work; :8080 never comes up) |
| **Status** | Closed — **shipped in v0.8.6** |
| **Summary** | `active-engine.env` sets `STICKLLM_ACTIVE_ENGINE=ninfer-all` for systemd. `stickllm_experimental.ACTIVE_ENGINE_PATH` also read that same env var as the **JSON file path**, so serve looked for a file named `ninfer-all`, defaulted to llama.cpp, and exited (`active engine is llama.cpp — use stickllm-llama.service`). Crash-loop / inactive; Models Load also fails because GGUF Activate is blocked while “NInfer is default” and nothing is on :8080. |
| **Fix** | Path env is `STICKLLM_ACTIVE_ENGINE_FILE` only; engine id keeps `STICKLLM_ACTIVE_ENGINE`. Unit: `test_active_engine_env_id_does_not_override_json_path`. |
| **Resolution** | Shipped in v0.8.6 ISO.


### ISS-041 — NInfer models via Models page (same path as llama); Set-default copy
| | |
|---|---|
| **ID** | ISS-041 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / NInfer-all / Models |
| **Severity** | MED (engine installed; weights UX is invisible / GGUF-only) |
| **Status** | Closed — **shipped in v0.8.6** |
| **Summary** | NInfer Set default toast/dialog implies a single auto `qwen38-27b` (~19 GiB) into a side path. Product: after Set default, user must **download a compatible NInfer model** like any other model — **no hard-coded default weight**. Models page filters by **active engine** (NInfer → NInfer-compatible only; llama.cpp → GGUF). **Storage path is the same as llama/GGUF downloads** (StickLLM models dir / Downloads queue), not a separate `experimental/ninfer-models` silo. Today lab DL uses `download-model.sh` → `/mnt/stickllm-data/experimental/ninfer-models/` and Models stays GGUF-only. |
| **Fix (v0.8.6)** | (1) **Copy:** Experimental Set default Confirm + success toast: engine is default on :8080; **download a compatible NInfer model from Models** before chat works; do **not** name only `qwen38-27b` / imply auto-download of one pin. (2) **Models:** when `active_engine=ninfer-all`, catalog + filters show NInfer-compatible artifacts; llama default → GGUF as today. (3) **Path:** enqueue/install into the **same models directory** as GGUF; `NINFER_MODEL_DIR` / serve points there. (4) Activate selects which `.ninfer` NInfer serves. Strata same pattern later. |
| **Resolution** | Shipped in v0.8.6 ISO.


### ISS-040 — Agent Zero work files are undiscoverable in Files / Office
| | |
|---|---|
| **ID** | ISS-040 |
| **Date** | 2026-11-23 |
| **Mode** | Local kiosk / Files / Office |
| **Severity** | MED (files exist in vault but users cannot find them) |
| **Status** | Closed — **shipped in v0.8.6** |
| **Summary** | Agent Zero writes user artifacts under `/a0/usr/workdir` → `vault/addons/agent-zero/work`. StickLLM Files only exposed Home / Vault / SSD apps, so opening Vault meant digging `addons/agent-zero/work`. Office “choose file” shows the raw `/var/lib/stickllm/vault/...` path. Nobody finds that without help. |
| **Fix** | Files gains an **Agent Zero** root (same folder) and opens there by default when the vault is unlocked. Carry: optional desk shortcut; teach A0 / `open_document` to prefer `vault/Documents` for user-facing PDFs. |
| **Resolution** | Shipped in v0.8.6 ISO.


### ISS-039 — Minesweeper intermittent open on LAN / StickLink browser
| | |
|---|---|
| **ID** | ISS-039 |
| **Date** | 2026-11-23 |
| **Mode** | Local / LAN browser desk |
| **Severity** | MED (opens sometimes; blank/401 or half-loaded board other times) |
| **Status** | Closed — **shipped in v0.8.6** |
| **Summary** | Minesweeper (and other `/apps/*`) intermittently fail to open in a paired LAN browser: race between `primeAppsSession` cookies and WinBox iframe navigation (401 JSON), shared `openApp._pairing` opening the wrong app, and parallel script fetches dropping a file through StickLink. |
| **Fix** | Per-id pair gate + await apps-session before iframe; iframe 401 retry; sequential minesweeper script loader with retry. Tracked in [docs/NEXT-0.8.5.md](docs/NEXT-0.8.5.md) carry-forward **MS1**. |
| **Resolution** | Shipped in v0.8.6 ISO.


## Closed (v0.8.5)

### ISS-038 — Agent Zero on v0.8.4: USB exec bits + first-boot online deps + false “Preload completed”
| | |
|---|---|
| **ID** | ISS-038 |
| **Date** | 2026-11-22 |
| **Mode** | Local / Agent Zero / USB docker graph |
| **Severity** | HIGH (A0 never binds `:5099` offline or after graph mode loss; lab “unstick” can leave UI stopped) |
| **Status** | Closed — **shipped in v0.8.5** |
| **Summary** | Three separate failures stacked on the v0.8.4 Lexar lab stick. (1) Exec bits were lost when the docker graph was written to USB (`/mnt/stickllm-data/stickllm-docker`); `run_ui` exited **126** until layer dirs were `chmod`’d. (2) `stickllm-agent run` does `docker rm -f` + `docker run` on every start, so A0 re-runs runtime installs each boot (`_05_framework_dependencies` → uv `filelock`/`fsspec` → “Restarting process…”, then Local TTS `en-core-web-sm` from GitHub, plus `/opt/venv-a0/bin/uv` symlink). Online ≈68 s to health 200; offline fails/hangs and **5099 never binds**. (3) “Preload completed” is from `preload.py` in parallel — **not** end of startup. Lab `_unstick_a0_hang.py` stopped `run_ui` (exit 241) and never restarted it; `supervisorctl start run_ui` brought it up in ~11 s; with deps already present, `docker restart` → health 200 in ~19 s. |
| **Notes** | Noise only: `the_listener` “No module named 'supervisor'”; searxng “dubious ownership”. **What fixed the running stick:** chmod on container/graph exec bits; one online first-start so downloads finished; `supervisorctl start run_ui` after the killed unstick. **v0.8.5 must:** (1) bake into the A0 image framework deps `_05` wants, `en_core_web_sm` 3.8.0, uv symlink, MiniLM/HF cache — then re-pin digest in image-ready; **or** make `_05` + Local TTS prep no-ops when offline; (2) preserve file modes when writing the docker graph to USB (`rsync -a` / `tar --same-permissions`) + build check `test -x /opt/pyenv/versions/3.12.4/bin/python3.12` inside the container; (3) run `the_listener` under `/usr/bin/python3` or install supervisor in its venv; (4) offline VM gate (no NIC): `/api/health` 200 within 60 s of sys. |
| **Resolution** | Shipped in v0.8.5 ISO (A0 exec bits + offline first-start).


### ISS-037 — Forgotten / corrupt vault passcode deadlocks first-boot setup (Delete vault + Skip) — **must ship in v0.8.5**
| | |
|---|---|
| **ID** | ISS-037 |
| **Date** | 2026-11-22 |
| **Mode** | Local / kiosk first-boot setup |
| **Severity** | HIGH (stick unusable until vault blob deleted by hand) |
| **Status** | Closed — **shipped in v0.8.5** |
| **Summary** | If the vault is corrupt/unreadable, or the password is wrong/forgotten, setup sticks on the vault screen with no way forward. Pre-hotfix UI hid Skip; “Skip” / “Full setup” still looped into unlock-only via `maybeOfferSetupOrUnlock` when `probe.found \|\| st.blob`. Operator needs an in-product **Delete vault and start fresh** path, then Create or Skip. |
| **Fix (v0.8.5)** | **(1) UI.** On vault unlock/setup, show **Delete vault and start fresh** when the vault won’t open (corrupt/unreadable), after a wrong password, and via a **Forgot password?** link next to the password field. **(2) Confirm.** Warning: “This permanently erases the vault and everything in it (chats, saved settings, keys). It can't be undone.” Checkbox “I understand this erases my vault”; **Delete** disabled until checked; **Cancel**. No typed confirmation words. **(3) Delete action.** Remove vault container, header and key files, and any mount/mapping. Stop dependent services cleanly first; show progress “Deleting vault…”. Leave models and the rest of the stick alone. **(4) After.** Setup continues with **Create new vault** or **Skip (no vault)**. Skip must finish setup without a vault (no re-entry into unlock-only). **(5) Audit.** Log delete time + reason (`corrupt` / `wrong_password` / `forgotten`); never log password or key material. |
| **VM gate** | Corrupt vault file → boot → Delete shows → delete → finish via **Create** and via **Skip**. Wrong password ×3 → Forgot password → Delete → setup finishes. Normal path: correct password still unlocks; Delete does not get in the way. |
| **Notes** | Repro (v0.8.4 Lexar lab, 2026-11-22): vault pointer at wiped MODELS USB; unlock failed forever; Skip returned to unlock gate. Lab escape was SSH delete of blob + pointers. In-tree start: `skipVaultSetupForNow`, `app.js?v=v084vaultskip` — must survive probe loop and ship with Delete. |
| **Resolution** | Shipped in v0.8.5 ISO (Delete vault + Skip in setup).


## Closed (v0.7.5)

### ISS-035 — v0.7.2 TEST ISO missing stickllm-sticklink-lab-grant (A0 never loads after Method C pair)
| | |
|---|---|
| **ID** | ISS-035 |
| **Date** | 2026-11-08 |
| **Mode** | StickLink Method C / lab-assisted |
| **Severity** | HIGH (pair can succeed; Agent Zero UI stays blank) |
| **Status** | Closed — **shipped in v0.7.5** |
| **Summary** | Gateway documents `/api/pair/sticklink-lab` + sudoers allow `stickllm-sticklink-lab-grant`, but the grant helper was absent from `overlay/usr/local/bin` on the v0.7.2 TEST ISO. Lab peer then dies after Noise when minting the A0 Bearer. |
| **Notes** | Script shipped under `overlay/usr/local/bin/stickllm-sticklink-lab-grant` in v0.7.5. Explains operator “paired but Agent Zero did not load” on earlier TEST ISOs. |
| **Resolution** | Shipped stickllm-sticklink-lab-grant in v0.7.5 bake.


## Closed (v0.7.1)

### ISS-032 — StickLink on stick: sticklinkd missing host Python deps
| | |
|---|---|
| **ID** | ISS-032 |
| **Date** | 2026-11-08 |
| **Mode** | Local / StickLink |
| **Severity** | HIGH (StickLink dead on v0.7.0 lab stick) |
| **Status** | Closed — **shipped in v0.7.1** |
| **Summary** | `sticklinkd` + `/etc/sticklink/sticklinkd.json` present on lab stick, but `sticklinkd --help` fails: `ModuleNotFoundError: No module named 'cryptography'`. Package list never included `python3-cryptography` / `python3-nacl` / `python3-websockets`. |
| **Notes** | Per product call: no in-place pip/hotfix chase — bake **v0.7.1** with those packages in `live-build/package-lists/stickllm.list.chroot`, flash, retry StickLink. |
| **Resolution** | Shipped python3-cryptography/nacl/websockets in v0.7.1 ISO.


## Closed (v0.3.9)

### ISS-020 — Next ISO: drop baked Qwen2.5-7B Q5_K_M (keep ~2 GB 3B)
| | |
|---|---|
| **ID** | ISS-020 |
| **Mode** | all / build |
| **Severity** | PRODUCT (P0 next ship after v0.3.8) |
| **Status** | Closed — **shipped in v0.3.9** |
| **Summary** | Next version: stop baking **Qwen2.5-7B Instruct Q5_K_M** (~5 GB split GGUF) into the ISO. Keep **Qwen2.5-3B Instruct Q4_K_M** (~2 GB) as the built-in test/default model. Users download 7B (and larger) via the hash-pinned catalog. |
| **Notes** | Touches when implementing (not now): `models/qwen2.5-7b-instruct-q5_k_m-*.gguf`, `scripts/download-model.sh`, `scripts/build.sh` + `scripts/lib/docker-build-live.sh` (`MODEL_SHARD*`), `config/models/catalog.toml` (`qwen25-7b-q5km` notes / bake wording — keep as **downloadable** pin), `config/profiles/amd-rtx3090.toml`, docs (`MODELS.md`, `BUILD.md`, `HARDWARE.md`). `overlay/etc/stickllm/default-model.env` already points at 3B. Leave shipping `out/v0.3.8/`, checksums, and Drive ISO alone. |
| **Resolution** | Done in v0.3.9: 3B baked; 7B Q5 download-only.


## Closed (v0.8.8 ISO — c5aa2305…)

### ISS-073 — Pipeline persist: async HF→RAM while USB drains, then RAM→GPU
| | |
|---|---|
| **ID** | ISS-073 |
| **Date** | 2026-11-23 |
| **Mode** | Models / Downloads / stage / NInfer |
| **Severity** | HIGH (USB serializes the whole pull; download end should ≈ USB caught up) |
| **Status** | Closed — **shipped in v0.8.8 ISO** (`c5aa2305…`)|
| **Summary** | Design agreed: during `land=ram+usb`, download HF→RAM at full speed while a **background drain mirrors to USB** so when the network finish lands, USB is (nearly) caught up — then RAM→GPU Load. Today persist is mostly post-download `persist_staged_to_usb` (second serial USB pass). Also block/warn high-ctx Load until headroom is safe (pairs with ISS-071/072 minimum guard). |
| **Fix (v0.8.8)** | Async USB mirror during ram+usb download (pipeline, not only after verify). Keep Load gated: refuse/warn while persist in flight or `MemAvailable < need + HEADROOM` for requested ctx. Do not redownload to prove; lab on existing stick. |

### ISS-072 — NInfer Advanced context slider stuck at 32K
| | |
|---|---|
| **ID** | ISS-072 |
| **Date** | 2026-11-23 |
| **Mode** | Models / Experimental / NInfer |
| **Severity** | MED (Context under Advanced cannot move; Load always 32K) |
| **Status** | Closed — **shipped in v0.8.8 ISO** (`c5aa2305…`)|
| **Summary** | ISS-058 showed Context + Advanced under NInfer and wired Load → `--max-context`/`--kv-capacity`, but `ninfer_catalog_rows` never set `ctx_max`. UI `syncModelActions` fell back to `32768`, so `#ctx.min === #ctx.max` and the slider could not move. llama.cpp VRAM/KV preset math also pinned NInfer presets at the floor on large packs. |
| **Fix (v0.8.8)** | Catalog/disk NInfer rows expose `ctx_max`/`max_context` **131072**. UI defaults NInfer missing max to 128K; NInfer presets use static 32K/64K/128K (no llama KV fit). Load still passes `ctx_size` (≥32K) into activate → `active-engine` / `model.env` → serve flags. Do **not** reopen ISS-058. **Minimum Load guard:** refuse activate while USB persist is in progress, or when `MemAvailable < KV(ctx)+HEADROOM` (plus file size if still USB-only). **Guard must prefer existing tmpfs stage** (`find_existing_staged`) so a USB `model_dir` hit does not add file size on top of MemAvailable that already reflects shm — otherwise 64K falsely refuses on a 62 GiB box with 27B already staged. |
| **Lab (2026-11-23)** | User Reload at **64K** coincided with hung `ninfer-serve` stop (SIGKILL after timeout), control/ui down (dead kiosk). **Model not lost:** USB `/mnt/stickllm-data/models/qwen3_6_27b.ninfer` and shm stage both **17495538688**. Orphan `/mnt/stickllm-data/qwen3_6_27b.ninfer.partial` deleted after size confirm. High-ctx Load guard landed in control (lab hotfix); full async pipeline → **ISS-073**. **Lab (same day, Load refuse):** activate 64K → exact error `Not enough free RAM for 65536 context (need ~37.2 GiB, MemAvailable 34.1 GiB)` with `already_ram: false` while 17 G lived in `/dev/shm` — **false positive** (USB path double-counted file size). After `_ninfer_resolve_ram_artifact`, need ≈ **20.9 GiB** vs MemAvailable **~34 GiB** → **64K should fit** on this 62 GiB + staged 27B box; Load 64K succeeded (`--max-context 65536`). User dropping to 32K also worked (true for that lower ctx). Refuse copy clarified: “Context NK is too large for free RAM… try 32K” (not vague stick-broken RAM failure). **VRAM ceiling (RTX 3090 24 GiB, qwen36-27b):** 64K ≈ **~20 GiB** VRAM works; **~96K** (`max-context 96256`) loads healthy at **~22.3 GiB** used; **128K fails** — weights ~15.3 GiB then engine exits (`runtime reservation requires ~8.5 GiB, only ~8.0 GiB available`); VRAM spikes then drops; host MemAvailable guard still **passes** 128K (system RAM ≠ VRAM). Optional bake: Advanced context warn near VRAM ceiling (host-RAM refuse copy alone is misleading). |

### ISS-071 — RAM-land download/Load: reserve + headroom + soft lock (spike guard)
| | |
|---|---|
| **ID** | ISS-071 |
| **Date** | 2026-11-23 |
| **Mode** | Models / Downloads / stage |
| **Severity** | HIGH (mid-download RAM spike can ENOSPC/OOM tmpfs `.part` before USB persist — lose progress) |
| **Status** | Closed — **shipped in v0.8.8 ISO** (`c5aa2305…`)|
| **Summary** | ISS-070 lands in tmpfs but only checks MemAvailable at start. A later RAM spike can fill `/dev/shm` or OOM curl; USB persist never runs; partial is volatile. Need a hold for the download/Load window, then release. |
| **Fix (v0.8.8)** | Keep **`HEADROOM_BYTES` (~10 GiB)** gate: only `ram+usb` / stage when `MemAvailable ≥ need + HEADROOM` **and** tmpfs free ≥ need. On accept: **`fallocate`/pre-size** the full artifact on the stage dir (reserve bytes so peers cannot steal them). Soft **RAM-busy lock** while `land=ram+usb` downloading or while a stage Load is in flight — refuse/queue other heavy stage/Load. On success: **persist USB ASAP**, then release lock + drop reservation extras; Unload still frees stage. Prefer reserve+soft-lock over whole-file `mlock` for the growing download; optional pin of the **completed** stage during Load only, unlock on Unload. |
| **Lab (2026-11-23)** | Proved why this matters: 64K NInfer Reload + desk left kiosk dead (control/ui stopped; exp-engine stop timeout SIGKILL). Fear was shm wipe before USB finish — **this time USB already complete** (`models/qwen3_6_27b.ninfer` = 17495538688, `land=ram+usb` state `done`). Still require **persist-asap + fsync before allowing heavy Load**, and soft-lock so a Load cannot race a mid-persist; leftover `qwen3_6_27b.ninfer.partial` (~15 GiB) under DATA root shows a prior incomplete write path. |

### ISS-070 — Download should land in free RAM and persist to USB (not USB twice)
| | |
|---|---|
| **ID** | ISS-070 |
| **Date** | 2026-11-23 |
| **Mode** | Models / Downloads / stage |
| **Severity** | HIGH (USB at 100% on download, then again on stage/Load — doubles flash bottleneck) |
| **Status** | Closed — **shipped in v0.8.8 ISO** (`c5aa2305…`)|
| **Summary** | Product intent: if you’re downloading a model you will Load it next. Today download writes only to USB, then ISS-053 stages USB→RAM — flash is the bottleneck twice. Wanted: when free RAM allows, **land the download in tmpfs and also persist to USB**; Load reads RAM. If RAM is tight, USB-only fallback. |
| **Fix (v0.8.8)** | `can_land_download` + GGUF `STICKLLM_DOWNLOAD_MIRROR`; NInfer `NINFER_MODEL_DIR`→tmpfs then `persist_staged_to_usb`. Load skips USB→RAM when already staged. Catalog/`find_ninfer_artifact` also scans tmpfs stage dirs so Models shows installed (Load) while USB persist is still copying; progress note **Saving to USB** (not a second Download). |

### ISS-069 — Models shows “Downloading Qwen2.5-7B” during NInfer pull
| | |
|---|---|
| **ID** | ISS-069 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / Models / Downloads |
| **Severity** | MED (wrong download name; looks like GGUF is pulling while NInfer is) |
| **Status** | Closed — **shipped in v0.8.8 ISO** (`c5aa2305…`)|
| **Summary** | Under NInfer, Models sticky/bar said **Downloading Qwen2.5-7B Instruct Q5_K_M** while the real job was `qwen36-27b` (~48%). Cause: leftover GGUF `*.partial` made `download_progress()` invent `state=downloading` (“partial on disk”) with no curl; status preferred that over live NInfer. |
| **Fix (v0.8.8)** | `download_progress`: idle when partial exists but curl is not running. Status prefers live NInfer bar when GGUF curl is not running. UI under NInfer labels from NInfer `download`/`queue` only — never a GGUF partial name. |

### ISS-068 — NInfer download queue missing Stop / Resume / Delete
| | |
|---|---|
| **ID** | ISS-068 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / Models / Downloads |
| **Severity** | MED (cannot pause a long NInfer profile pull; was present in prior hotfix) |
| **Status** | Closed — **shipped in v0.8.8 ISO** (`c5aa2305…`)|
| **Summary** | Downloads queue hid Stop/Start/Delete for NInfer (`queueable: false`). Engine UX parity: same pause/resume/remove as GGUF. |
| **Fix (v0.8.8)** | UI shows Stop / Resume / Delete for NInfer rows. `queue_stop`/`queue_start`/`queue_remove` kill/restart `download-model.sh` and persist `paused` in `ninfer-model-download.json` (wrapper must not flip Stop → failed). |



### ISS-067 — Desk shows wrong local time (Timezone stuck on Etc/UTC)
| | |
|---|---|
| **ID** | ISS-067 |
| **Date** | 2026-11-23 |
| **Mode** | Boot / desk / NTP |
| **Severity** | HIGH (looks like clock broken; TLS ok but desk/XFCE time wrong) |
| **Status** | Closed — **shipped in v0.8.8 ISO** (`c5aa2305…`)|
| **Summary** | After flash, NTP can sync while Timezone stays `Etc/UTC`, so the desk clock shows UTC instead of local. Must **not** hard-lock to Eastern or any single zone. |
| **Fix (v0.8.8)** | `stickllm-clock-sync`: on **first internet connect** while still UTC, set timezone from public-IP geolocation (ipapi / worldtimeapi / ipinfo), persist to `/var/lib/stickllm/timezone`. No `America/New_York` / `Etc/UTC` default. HTTP Date fallback for wall-clock when NTP unsynced or drift >90s. |



### ISS-066 — NInfer profile download does not pass saved HF token
| | |
|---|---|
| **ID** | ISS-066 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / Models / NInfer |
| **Severity** | MED (slower downloads; gated/uncensored HF repos fail without token) |
| **Status** | Closed — **shipped in v0.8.8 ISO** (`c5aa2305…`)|
| **Summary** | GGUF / shared Downloads queue exports `STICKLLM_HF_TOKEN` for curl. Official NInfer pins via `download-model.sh` did not — saved Models HF token was ignored. Token matters for **speed** (fast with token, slow without) and gated repos. UI wrongly said catalog downloads need no token. |
| **Fix (v0.8.8)** | Pass `HF_TOKEN` / hub / `STICKLLM_HF_TOKEN` into NInfer download wrapper. UI: hint + Test say token speeds downloads; Test calls `test_hf_token` (whoami); start-download note warns when no token saved. |



### ISS-065 — Switch to NInfer shows “loading Qwen2.5” while downloading .ninfer
| | |
|---|---|
| **ID** | ISS-065 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / Models / NInfer |
| **Severity** | MED (false status; looks like wrong model is loading) |
| **Status** | Closed — **shipped in v0.8.8 ISO** (`c5aa2305…`)|
| **Summary** | After Set default → NInfer, tray/status shows **loading Qwen2.5…** (parked GGUF `model.env`) while exp-engine activates or a `.ninfer` download runs. |
| **Fix** | Park GGUF `model.env` on NInfer Set-default (restore on llama.cpp). `active_model_identity` ignores GGUF leftovers when `model_key` empty. UI: under NInfer show download progress / “none”, never “loading” a GGUF name from unit busy. Related false **download** name → **ISS-069**. |

## Closed (v0.8.7 ISO — 5e554919…)

### ISS-064 — A0-created files not downloadable on phone over StickLink
| | |
|---|---|
| **ID** | ISS-064 |
| **Date** | 2026-11-23 |
| **Mode** | Agent Zero / StickLink |
| **Severity** | MED (PDF/Doc created on stick unreachable from phone) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | Files Agent Zero creates (PDF, Doc, etc.) should be downloadable from A0’s UI through the paired StickLink session. Today the phone cannot pull those artifacts over the link. |
| **Fix (v0.8.7)** | Mux: 32 MiB body cap; never gzip attachments / `download_work_dir_file`; 300s bridge timeout; `x-sticklink-download` + Content-Disposition preserved. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-063 — Oversized phone images overflow vision context
| | |
|---|---|
| **ID** | ISS-063 |
| **Date** | 2026-11-23 |
| **Mode** | Agent Zero / StickLink / vision |
| **Severity** | HIGH (full-size photos blow context; OCR loop on failure) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | Gateway should shrink oversized images before Agent Zero’s vision tool sees them. If vision still fails, A0 should report failure (prompt/settings) instead of looping on OCR. |
| **Fix (v0.8.7)** | StickLLM attach-images extension: PIL resize ≤1280 JPEG data URL before history inject. Profile prompt: say vision failed once — no OCR loop. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-062 — A0 syncStore handshake NO_HANDLERS over StickLink
| | |
|---|---|
| **ID** | ISS-062 |
| **Date** | 2026-11-23 |
| **Mode** | Agent Zero / StickLink |
| **Severity** | HIGH (red sync dot; falls back to slow polling) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | Over the link, Agent Zero logs `[syncStore] handshake failed: state_request failed: NO_HANDLERS`. Red sync indicator stays on; polling fallback. |
| **Fix (v0.8.7)** | Gateway rewrites served sync/websocket JS: force `ws_webui` in auth.handlers, 20s `state_request` timeout, process `state_push` while DEGRADED. Do **not** patch Agent Zero upstream. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-061 — StickLink session drops ~every 90s under load
| | |
|---|---|
| **ID** | ISS-061 |
| **Date** | 2026-11-23 |
| **Mode** | StickLink |
| **Severity** | HIGH (phone sess lost; no pong path for 90s) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | Under load, StickLink to phone goes quiet ~every 90s. Phone log: `sess lost: no pong path for 90s`; sometimes nothing received from stick. Repro window ~2026-11-23 17:29–17:32 ET — check stick link/relay logs. |
| **Fix (v0.8.7)** | `ingest_transport_wire` answers ping/pong immediately (before mux queue) so heavy Agent Zero loads cannot starve the phone’s 90s pong watchdog. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-060 — Sticky Load under NInfer calls llama activate → “unknown model”
| | |
|---|---|
| **ID** | ISS-060 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / Models / NInfer |
| **Severity** | HIGH (Load broken for every NInfer card) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | With NInfer selected, sticky **Load model** / card Load hit `#activate` → `model_activate` (llama catalog). HF / disk `.ninfer` ids (e.g. Inkling) fail with **unknown model**. |
| **Fix (v0.8.7)** | Card Load + `#activate` under `ninfer-all` call `loadNinferModel` → `experimental_ninfer_model_activate` (stage + serve). Do not route NInfer ids through llama `model_activate`. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-059 — NInfer Models search is only 3 pinned Qwen ids, not Hugging Face
| | |
|---|---|
| **ID** | ISS-059 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / Models / NInfer |
| **Severity** | MED (HF site shows dozens of `.ninfer`; StickLLM shows 3) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | Under NInfer, Browse/search only filters `NINFER_MODEL_CATALOG` (qwen38-27b, qwen36-27b, qwen36-35b-a3b) — the ids NInfer’s `download-model.sh` knows. UI explicitly says “not HF”. Hugging Face search for “ninfer” returns many community `.ninfer` artifacts the stick never queries. |
| **Fix (v0.8.7)** | Engine-scoped HF search for `.ninfer` (same trust/fit filters as GGUF path). Keep the 3 official profiles pinned. Download → shared models dir via Downloads queue; Load via experimental serve (not only the 3 shell script ids). |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-058 — Models Context + Advanced hidden for non-llama engines
| | |
|---|---|
| **ID** | ISS-058 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / Models |
| **Severity** | MED (engine UX parity broken; ctx stuck at bake default) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | With NInfer (and any non-llama default), Models hides `#localTune`, so Context size, presets, KV, and Advanced disappear. llama.cpp shows them. Product: same config panel for every engine; grey only knobs that engine cannot honor. |
| **Fix (v0.8.7)** | Stop hiding the whole panel by engine. Show `#localTune` whenever a local/installed model is selected. Wire Context (≥32768 floor) into NInfer `--max-context`/`--kv-capacity` (model.env + active-engine). KV type greyed under NInfer. Chat sampling knobs still apply; A0 ctx follows live engine (≥32K). |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-057 — A0 vision forced true for every NInfer
| | |
|---|---|
| **ID** | ISS-057 |
| **Date** | 2026-11-23 |
| **Mode** | Agent Zero / NInfer |
| **Severity** | LOW (wrong modality; some models text-only) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | Sync set vision=true for all NInfer loads; text-only profiles should follow `/v1/models` modalities. |
| **Fix (v0.8.7)** | `_model_vision` / sync reads modalities from engine `/v1/models` (and mmproj for llama). |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-056 — A0 LiteLLM fails on host.docker.internal
| | |
|---|---|
| **ID** | ISS-056 |
| **Date** | 2026-11-23 |
| **Mode** | Agent Zero / NInfer |
| **Severity** | HIGH (kiosk A0 chat broken after NInfer Load) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | A0 `model_providers.yaml` used `http://host.docker.internal:8080/v1`; LiteLLM could not resolve/reach it on StickLLM docker bridge → UI errors. |
| **Fix (v0.8.7)** | Patch api_base to `172.30.0.1:8080`; `stickllm-agent` `--add-host host.docker.internal:host-gateway`. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-055 — A0 model id mismatch vs NInfer `/v1/models`
| | |
|---|---|
| **ID** | ISS-055 |
| **Date** | 2026-11-23 |
| **Mode** | Agent Zero / NInfer |
| **Severity** | HIGH (404 / wrong model; chat naming and chat fail) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | StickLLM used `qwen36-27b` / leftover `stickllm` while NInfer advertises `qwen3.6-27b` (and similar). Sync did not normalize. |
| **Fix (v0.8.7)** | `_model_matches` collapses punctuation; sync util/chat to live `/v1/models` id. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-054 — NInfer bare serve 8K broke StickLLM/A0 32K floor
| | |
|---|---|
| **ID** | ISS-054 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / NInfer / Agent Zero |
| **Severity** | HIGH (LiteLLM `context_length_exceeded`; A0 unusable) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | Product hard floor is 32K. Bare `ninfer-serve` defaulted `--max-context` 8192 while A0/presets used 32768 → engine rejected long prompts. |
| **Fix (v0.8.7)** | `stickllm-experimental-serve` always passes `--max-context` and `--kv-capacity` ≥32768; A0 sync keeps ctx 32768. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-053 — USB Load slow; stage to RAM then load (reclaimable)
| | |
|---|---|
| **ID** | ISS-053 |
| **Date** | 2026-11-23 |
| **Mode** | Models / Local / Experimental |
| **Severity** | MED (Load stuck ~90% for minutes on USB; looks hung) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | Large GGUF/NInfer Load reads weights from USB flash; GPU idle until copy done. User asked USB→RAM then load; do not mlock; free when Unload/switch/pressure. Lab: Download staged Inkling to `/dev/shm`, then Load ignored it and re-copied USB→`/tmp` (stuck ~90%) so engine still read USB. |
| **Fix (v0.8.7)** | `stickllm_stage.py` + control hooks: stage to `/tmp` or `/dev/shm` (not tiny `/run`); gateway/UI status bar %; free_stage on unload; reclaim_if_low_ram. Apply on Load and after Download when RAM allows. **Reuse:** before any new copy, `find_existing_staged` across all stage dirs; drop orphan `.partial`s; never duplicate a complete RAM copy just because `/tmp` has more free than `/dev/shm`. **UI:** gateway `experimental_ninfer_model_activate` timeout 7200s (180s was clearing Loading mid-copy); status chip follows `health.stage` (“Copying from USB to RAM…”) even after activate returns. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-052 — NInfer HF search / pills show GGUF as NInfer
| | |
|---|---|
| **ID** | ISS-052 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / Models |
| **Severity** | MED (wrong artifact type; Inkling looked like NInfer) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | With NInfer default, search/pills labeled or queued GGUF/HF rows as NInfer (e.g. WaveCut Inkling). User: shouldn’t show GGUF when NInfer search; same experience + trust filters per engine. |
| **Fix (v0.8.7)** | Engine-scoped catalog + HF search; GGUF path when row is GGUF; NInfer `.ninfer` when NInfer. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-051 — “unknown NInfer model” blocked downloads (Inkling etc.)
| | |
|---|---|
| **ID** | ISS-051 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / Models |
| **Severity** | MED (hard refuse; user can't download) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | With NInfer default, Download for GGUF/HF names (e.g. Inkling) hit `unknown NInfer model` and stopped. |
| **Fix (v0.8.7)** | Soft gate: GGUF rows warn then queue as GGUF; unlisted NInfer ids warn then still call download-model.sh. Never hard-block. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-050 — Experimental settings lost on reboot (NInfer / GPU unlock)
| | |
|---|---|
| **ID** | ISS-050 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / Local |
| **Severity** | HIGH (Set default + unlock vanish every reboot) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | NInfer default, GPU unlock, and engine state lived under `/var/lib/stickllm/experimental` on the live overlay → wiped on reboot. Models fell back to GGUF/llama.cpp. |
| **Fix (v0.8.7)** | `stickllm-experimental-host`: bind-mount DATA `experimental/lib` → `/var/lib/…/experimental`. **Same machine** keeps settings; **different machine** resets to llama.cpp + unlocks off (engines downloads kept). |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-049 — Setup “Open now” gives no feedback while model loads
| | |
|---|---|
| **ID** | ISS-049 |
| **Date** | 2026-11-23 |
| **Mode** | Local / first-boot setup |
| **Severity** | LOW (looks stuck; load still works) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | First-boot Open model → **Open now** sits idle until activate returns, then advances. No Loading… on the button. |
| **Fix (v0.8.7)** | Immediate **Loading…** + status line; disable button until activate settles or fails. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-048 — Power off OK popup hidden behind Browser
| | |
|---|---|
| **ID** | ISS-048 |
| **Date** | 2026-11-23 |
| **Mode** | Local / desk |
| **Severity** | MED (power off looks broken; confirm stuck behind) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | Start → Power off used `window.confirm`. With Browser open, the OK dialog stayed on the desk Chromium window under the native X11 browser — user had to minimise to see it. |
| **Fix (v0.8.7)** | `yieldNative()` then in-desk `confirmBox` (expose on `stickApp`). |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-047 — Wrong wall clock after Wi‑Fi → TLS “could not connect”
| | |
|---|---|
| **ID** | ISS-047 |
| **Date** | 2026-11-23 |
| **Mode** | StickLink / Wi‑Fi / all |
| **Severity** | HIGH (TLS fails while clock is years off) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | Stick still has wrong time after Wi‑Fi; StickLink/HTTPS shows “could not connect to server.” `systemd-timesyncd` was After= masked `NetworkManager-wait-online`, so NTP often never ran when Wi‑Fi came up later. |
| **Fix (v0.8.7)** | Drop wait-online from timesyncd; `stickllm-clock-sync` on Wi‑Fi apply + NM dispatcher `99-stickllm-clock`; enable timesyncd in chroot hook. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-046 — Experimental engines must match llama.cpp Models UX
| | |
|---|---|
| **ID** | ISS-046 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / Models |
| **Severity** | MED (product consistency) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | NInfer/Strata should feel like llama.cpp on Models: same Download queue, **Load**/**Unload**, Loading % tray, A0 sync — not a separate “Activate” / silent USB wait path. |
| **Fix (v0.8.7)** | Parity pass: queue + Load wording + loading status + Unload stops exp-engine; Strata catalog later. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-045 — NInfer “Running” / “Open Model” / A0 “no model” while still loading
| | |
|---|---|
| **ID** | ISS-045 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / NInfer / Models / Agent Zero |
| **Severity** | MED (misleading status; A0 bridge until :8080 ready) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | After NInfer Load, card said **Running** as soon as `model_key` was set; tray stayed **Open Model**; A0 said no model. Reality: engine still loading weights from USB — `/health` not ok yet. Also used “Activate” instead of “Load”, and did not show GGUF-style Loading % (llama unit looked “dead”). |
| **Fix (v0.8.7)** | **Load** wording; `running` only when healthy; write `model.env` + A0 `sync-model`; tray Loading % / “Loading NInfer weights from USB…” via exp-engine unit + health poll. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


### ISS-044 — NInfer model downloads missing from Downloads queue
| | |
|---|---|
| **ID** | ISS-044 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / NInfer / Models |
| **Severity** | MED (download works; progress invisible in Downloads) |
| **Status** | Closed — **shipped in v0.8.7 ISO** (5e554919…) |
| **Summary** | On v0.8.6, Models → Download for a NInfer profile runs `download-model.sh` but never appears in the GGUF Downloads queue / progress bar. Users think nothing started. (Vision/mmproj chips stay llama.cpp-only — NInfer rows are `.ninfer`, not GGUF+mmproj.) |
| **Fix (v0.8.7)** | `ninfer_download_progress()` + merge into `status.download` / `status.download_queue`; UI polls and shows NInfer jobs on Downloads; keep NInfer catalog during poll. |
| **Resolution** | Shipped in StickLLM-v0.8.7.iso. Do not re-open; regressions get a new ISS id.


## Closed

### ISS-025 — Voice chat and load-meter hotfixes for v0.4.2
| | |
|---|---|
| **ID** | ISS-025 |
| **Mode** | Local / Server |
| **Severity** | PRODUCT |
| **Status** | Closed in v0.4.2 |
| **Summary** | Voice on/off with resident Whisper and Kitten, streaming speech, a stop button, a hidden brief prompt, an 80-token voice budget, thinking text skipped while Voice is on, and 1 second of silence auto-send after real speech. Vault chats can be deleted. Loading waits for a paired browser, and the meter does not jump to a fake 30%. |
| **Resolution** | In the v0.4.2 image. Speech files and `whisper-server` are baked. About and `stickllm.json` say v0.4.2. `out/v0.4.0` and `out/v0.4.1` were not changed. |

### ISS-024 — USB settings partition was left out of v0.4.1
| | |
|---|---|
| **ID** | ISS-024 |
| **Mode** | all / vault |
| **Severity** | PRODUCT |
| **Status** | Closed in v0.4.2. `out/v0.4.0` and `out/v0.4.1` were not changed |
| **Summary** | A ~256 MB settings partition on the boot USB, beside the live image, encrypted with the SSD vault passcode. Portable per-computer vault locations and portable secrets. Not a second password. |
| **Resolution** | The v0.4.2 image includes `stickllm-usb-claim` and `stickllm-usb-settings`. First boot reserves the partition raw on the boot USB and does not shrink an existing `STICKLLM-DATA`. The slot is LUKS-formatted with the vault passcode after the SSD vault accepts it, and the existing stick keyfile and recovery digest are added when those files are already present. Host `create-partition` stays disabled. The Hugging Face token is written on the settings partition once it is unlocked; chats stay in the SSD vault; voice weights stay in `/opt/stickllm/speech`. |
| **Notes** | Claim will not shrink a `STICKLLM-DATA` that already uses the whole stick. Encryption waits for vault setup/unlock (boot still must not ask for a passcode). The plaintext path hint on `STICKLLM-DATA` remains so Find existing vault works before settings is opened. There is no new UI for arbitrary secrets beyond the existing Hugging Face token field. `secret-set` is the command for other names. Machines with no DMI serial share one `unknown` location record. Opening an existing vault stays the steps in [docs/VAULT.md](docs/VAULT.md#opening-an-existing-vault). |

## Closed (v0.3.0)

### ISS-019 — GRUB theme selected entry invisible
| **Status** | Closed (v0.3) |
| **Resolution** | Removed empty `selected_item_pixmap_style`; set visible `selected_item_color = #7dffb3`. |

### ISS-018 — CPU fallback broken (no NVIDIA)
| **Status** | Closed (v0.3) |
| **Resolution** | Ship `llama-server-cpu`; `stickllm-llama-start` picks CUDA vs `-ngl 0`; no hard `/dev/nvidia*` unit deps; Running only after `/health`; RAM fits on CPU; gateway friendly errors. |
| **HW** | Validated on Asus laptop (no NVIDIA) with v0.3 apiready ISO. |

### ISS-011 — download-model sha256 only warned
| **Status** | Closed (v0.3) |
| **Resolution** | Missing/mismatched sha256 fatal; verify `.partial` before `mv`. |

### ISS-010 — Build cannot reproduce the working kiosk
| **Status** | Closed (v0.3) |
| **Resolution** | `docker-build-live.sh` copies `stickllm.list.chroot` (cage/chromium/seatd/libinput); kiosk script/unit in overlay + hook enable. |

### ISS-009 — Gateway pairing / token weaknesses
| **Status** | Closed (v0.3) |
| **Resolution** | Rate limit + code expiry; `hmac.compare_digest`; no plaintext pending token; CSP headers. |

### ISS-008 — sudoers NOPASSWD overly broad
| **Status** | Closed (v0.3) |
| **Resolution** | Narrow command list; remove sudo-group membership for `stickllm`/`user`. |

### ISS-007 — Hardcoded stickllm password + SSH password login
| **Status** | Closed (v0.3) |
| **Resolution** | Random per-boot SSH password via `stickllm-ssh-bootstrap`; shown on Term console. |

### ISS-006 — llama binds 0.0.0.0:8080 as root
| **Status** | Closed (v0.3) |
| **Resolution** | Bind `127.0.0.1` only; run as `stickllm-llama` (+ root ExecStartPre for modprobe). |

### ISS-005 — Server console download ETA stuck
| **Status** | Closed (v0.3) |
| **Resolution** | Stable ETA phase key + bytes-based ETA from `download-progress.json`. |

### ISS-003 — “API Key” naming confusing
| **Status** | Closed (v0.3) |
| **Resolution** | Removed API key copy/console hints (aligned with ISS-004). |

### ISS-002 — Server console refresh too aggressive
| **Status** | Closed (v0.3) |
| **Resolution** | bootstatus poll/repaint ~10s. |

### ISS-017 — Server/Term WiFi needs LAN browser (chicken-and-egg)
| **Status** | Closed (v0.3.1) |
| **Resolution** | Console `stickllm-wifi-setup` (tty2 / Term) writes same NM profile as Settings → Network; READY/motd document Local-first / Ethernet alternatives. Web Settings remains for when uplink already exists. Setup AP deferred. |

### ISS-001 — Web lookup broken on Local
| **Status** | Closed (v0.3) |
| **Resolution** | Local `ensure_network`; WiFi UI → NM profile on DATA; status `online` bit; Web needs uplink. |
| **HW** | Local WiFi validated on HW with v0.3 apiready ISO. |

### ISS-016 — Conflicting nvidia-drm modprobe confs
| **Status** | Closed (v0.3) |
| **Resolution** | Keep `stickllm-nvidia-drm.conf` only (v0.2 behavior); remove duplicate. |

### ISS-004 — Decide whether to keep/expose LAN OpenAI API
| **Status** | Closed (v0.3) |
| **Resolution** | External `/v1/chat/completions` returns 410 without StickLLM UI client header; UI uses `/api/chat`. |
