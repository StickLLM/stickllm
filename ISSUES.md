# StickLLM Issues Log

Lightweight product/bug log (same spirit as [FEATURES.md](FEATURES.md)). Not a GitHub Issues mirror.

**How to add an entry**
1. Pick the next `ISS-NNN` ID.
2. Put new open items at the top of **Open**.
3. Fill: ID, date, mode (Local / Term / Server / all), status, summary, notes/repro.
4. When fixed, move to **Closed** (or set status Closed) with a one-line resolution.

---

## Open

### ISS-043 — A0 “Automatic chat naming failed” on NInfer (empty content / thinking)
| | |
|---|---|
| **ID** | ISS-043 |
| **Date** | 2026-11-23 |
| **Mode** | Agent Zero / NInfer |
| **Severity** | MED (chat works; naming toast every turn) |
| **Status** | Baked in **v0.8.6** |
| **Summary** | With NInfer `qwen3.8-27b`, utility/chat-naming calls return empty `content` and fill `reasoning_content` (thinking). A0 only reads `content` → “Automatic chat naming failed (utility model busy or unreachable).” StickLLM already set LiteLLM `extra_body.chat_template_kwargs.enable_thinking=false` for Qwen3.5; **NInfer ignores `extra_body`** and needs top-level `enable_thinking: false` / `chat_template_kwargs`. Also sync util/chat model id to `/v1/models` id (`qwen3.8-27b`), not a leftover GGUF name. |
| **Fix** | `_util_model_kwargs` + `presets.yaml` pass top-level thinking-off as well as `extra_body`; sync-model after NInfer Set default. |

### ISS-042 — NInfer Set default never serves: STICKLLM_ACTIVE_ENGINE env path collision
| | |
|---|---|
| **ID** | ISS-042 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / NInfer |
| **Severity** | HIGH (Set default appears to work; :8080 never comes up) |
| **Status** | Baked in **v0.8.6** |
| **Summary** | `active-engine.env` sets `STICKLLM_ACTIVE_ENGINE=ninfer-all` for systemd. `stickllm_experimental.ACTIVE_ENGINE_PATH` also read that same env var as the **JSON file path**, so serve looked for a file named `ninfer-all`, defaulted to llama.cpp, and exited (`active engine is llama.cpp — use stickllm-llama.service`). Crash-loop / inactive; Models Load also fails because GGUF Activate is blocked while “NInfer is default” and nothing is on :8080. |
| **Fix** | Path env is `STICKLLM_ACTIVE_ENGINE_FILE` only; engine id keeps `STICKLLM_ACTIVE_ENGINE`. Unit: `test_active_engine_env_id_does_not_override_json_path`. |

### ISS-041 — NInfer models via Models page (same path as llama); Set-default copy
| | |
|---|---|
| **ID** | ISS-041 |
| **Date** | 2026-11-23 |
| **Mode** | Experimental / NInfer-all / Models |
| **Severity** | MED (engine installed; weights UX is invisible / GGUF-only) |
| **Status** | Baked in **v0.8.6** |
| **Summary** | NInfer Set default toast/dialog implies a single auto `qwen38-27b` (~19 GiB) into a side path. Product: after Set default, user must **download a compatible NInfer model** like any other model — **no hard-coded default weight**. Models page filters by **active engine** (NInfer → NInfer-compatible only; llama.cpp → GGUF). **Storage path is the same as llama/GGUF downloads** (StickLLM models dir / Downloads queue), not a separate `experimental/ninfer-models` silo. Today lab DL uses `download-model.sh` → `/mnt/stickllm-data/experimental/ninfer-models/` and Models stays GGUF-only. |
| **Fix (v0.8.6)** | (1) **Copy:** Experimental Set default Confirm + success toast: engine is default on :8080; **download a compatible NInfer model from Models** before chat works; do **not** name only `qwen38-27b` / imply auto-download of one pin. (2) **Models:** when `active_engine=ninfer-all`, catalog + filters show NInfer-compatible artifacts; llama default → GGUF as today. (3) **Path:** enqueue/install into the **same models directory** as GGUF; `NINFER_MODEL_DIR` / serve points there. (4) Activate selects which `.ninfer` NInfer serves. Strata same pattern later. |

### ISS-040 — Agent Zero work files are undiscoverable in Files / Office
| | |
|---|---|
| **ID** | ISS-040 |
| **Date** | 2026-11-23 |
| **Mode** | Local kiosk / Files / Office |
| **Severity** | MED (files exist in vault but users cannot find them) |
| **Status** | Baked in **v0.8.6** |
| **Summary** | Agent Zero writes user artifacts under `/a0/usr/workdir` → `vault/addons/agent-zero/work`. StickLLM Files only exposed Home / Vault / SSD apps, so opening Vault meant digging `addons/agent-zero/work`. Office “choose file” shows the raw `/var/lib/stickllm/vault/...` path. Nobody finds that without help. |
| **Fix** | Files gains an **Agent Zero** root (same folder) and opens there by default when the vault is unlocked. Carry: optional desk shortcut; teach A0 / `open_document` to prefer `vault/Documents` for user-facing PDFs. |

### ISS-039 — Minesweeper intermittent open on LAN / StickLink browser
| | |
|---|---|
| **ID** | ISS-039 |
| **Date** | 2026-11-23 |
| **Mode** | Local / LAN browser desk |
| **Severity** | MED (opens sometimes; blank/401 or half-loaded board other times) |
| **Status** | Baked in **v0.8.6** |
| **Summary** | Minesweeper (and other `/apps/*`) intermittently fail to open in a paired LAN browser: race between `primeAppsSession` cookies and WinBox iframe navigation (401 JSON), shared `openApp._pairing` opening the wrong app, and parallel script fetches dropping a file through StickLink. |
| **Fix** | Per-id pair gate + await apps-session before iframe; iframe 401 retry; sequential minesweeper script loader with retry. Tracked in [docs/NEXT-0.8.5.md](docs/NEXT-0.8.5.md) carry-forward **MS1**. |

### ISS-038 — Agent Zero on v0.8.4: USB exec bits + first-boot online deps + false “Preload completed”
| | |
|---|---|
| **ID** | ISS-038 |
| **Date** | 2026-11-22 |
| **Mode** | Local / Agent Zero / USB docker graph |
| **Severity** | HIGH (A0 never binds `:5099` offline or after graph mode loss; lab “unstick” can leave UI stopped) |
| **Status** | Open — root cause confirmed on running stick; target **v0.8.5** (see [docs/NEXT-0.8.5.md](docs/NEXT-0.8.5.md); checklist #35–37) |
| **Summary** | Three separate failures stacked on the v0.8.4 Lexar lab stick. (1) Exec bits were lost when the docker graph was written to USB (`/mnt/stickllm-data/stickllm-docker`); `run_ui` exited **126** until layer dirs were `chmod`’d. (2) `stickllm-agent run` does `docker rm -f` + `docker run` on every start, so A0 re-runs runtime installs each boot (`_05_framework_dependencies` → uv `filelock`/`fsspec` → “Restarting process…”, then Local TTS `en-core-web-sm` from GitHub, plus `/opt/venv-a0/bin/uv` symlink). Online ≈68 s to health 200; offline fails/hangs and **5099 never binds**. (3) “Preload completed” is from `preload.py` in parallel — **not** end of startup. Lab `_unstick_a0_hang.py` stopped `run_ui` (exit 241) and never restarted it; `supervisorctl start run_ui` brought it up in ~11 s; with deps already present, `docker restart` → health 200 in ~19 s. |
| **Notes** | Noise only: `the_listener` “No module named 'supervisor'”; searxng “dubious ownership”. **What fixed the running stick:** chmod on container/graph exec bits; one online first-start so downloads finished; `supervisorctl start run_ui` after the killed unstick. **v0.8.5 must:** (1) bake into the A0 image framework deps `_05` wants, `en_core_web_sm` 3.8.0, uv symlink, MiniLM/HF cache — then re-pin digest in image-ready; **or** make `_05` + Local TTS prep no-ops when offline; (2) preserve file modes when writing the docker graph to USB (`rsync -a` / `tar --same-permissions`) + build check `test -x /opt/pyenv/versions/3.12.4/bin/python3.12` inside the container; (3) run `the_listener` under `/usr/bin/python3` or install supervisor in its venv; (4) offline VM gate (no NIC): `/api/health` 200 within 60 s of sys. |

### ISS-037 — Forgotten / corrupt vault passcode deadlocks first-boot setup (Delete vault + Skip) — **must ship in v0.8.5**
| | |
|---|---|
| **ID** | ISS-037 |
| **Date** | 2026-11-22 |
| **Mode** | Local / kiosk first-boot setup |
| **Severity** | HIGH (stick unusable until vault blob deleted by hand) |
| **Status** | Open — **must be in v0.8.5**; partial lab mitigation only (Skip UI hotfix + manual blob delete); see [docs/NEXT-0.8.5.md](docs/NEXT-0.8.5.md) |
| **Summary** | If the vault is corrupt/unreadable, or the password is wrong/forgotten, setup sticks on the vault screen with no way forward. Pre-hotfix UI hid Skip; “Skip” / “Full setup” still looped into unlock-only via `maybeOfferSetupOrUnlock` when `probe.found \|\| st.blob`. Operator needs an in-product **Delete vault and start fresh** path, then Create or Skip. |
| **Fix (v0.8.5)** | **(1) UI.** On vault unlock/setup, show **Delete vault and start fresh** when the vault won’t open (corrupt/unreadable), after a wrong password, and via a **Forgot password?** link next to the password field. **(2) Confirm.** Warning: “This permanently erases the vault and everything in it (chats, saved settings, keys). It can't be undone.” Checkbox “I understand this erases my vault”; **Delete** disabled until checked; **Cancel**. No typed confirmation words. **(3) Delete action.** Remove vault container, header and key files, and any mount/mapping. Stop dependent services cleanly first; show progress “Deleting vault…”. Leave models and the rest of the stick alone. **(4) After.** Setup continues with **Create new vault** or **Skip (no vault)**. Skip must finish setup without a vault (no re-entry into unlock-only). **(5) Audit.** Log delete time + reason (`corrupt` / `wrong_password` / `forgotten`); never log password or key material. |
| **VM gate** | Corrupt vault file → boot → Delete shows → delete → finish via **Create** and via **Skip**. Wrong password ×3 → Forgot password → Delete → setup finishes. Normal path: correct password still unlocks; Delete does not get in the way. |
| **Notes** | Repro (v0.8.4 Lexar lab, 2026-11-22): vault pointer at wiped MODELS USB; unlock failed forever; Skip returned to unlock gate. Lab escape was SSH delete of blob + pointers. In-tree start: `skipVaultSetupForNow`, `app.js?v=v084vaultskip` — must survive probe loop and ship with Delete. |

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

### ISS-035 — v0.7.2 TEST ISO missing stickllm-sticklink-lab-grant (A0 never loads after Method C pair)
| | |
|---|---|
| **ID** | ISS-035 |
| **Date** | 2026-11-08 |
| **Mode** | StickLink Method C / lab-assisted |
| **Severity** | HIGH (pair can succeed; Agent Zero UI stays blank) |
| **Status** | Closed in **v0.7.5** bake (helper in overlay) |
| **Summary** | Gateway documents `/api/pair/sticklink-lab` + sudoers allow `stickllm-sticklink-lab-grant`, but the grant helper was absent from `overlay/usr/local/bin` on the v0.7.2 TEST ISO. Lab peer then dies after Noise when minting the A0 Bearer. |
| **Notes** | Script shipped under `overlay/usr/local/bin/stickllm-sticklink-lab-grant` in v0.7.5. Explains operator “paired but Agent Zero did not load” on earlier TEST ISOs. |

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

### ISS-032 — StickLink on stick: sticklinkd missing host Python deps
| | |
|---|---|
| **ID** | ISS-032 |
| **Date** | 2026-11-08 |
| **Mode** | Local / StickLink |
| **Severity** | HIGH (StickLink dead on v0.7.0 lab stick) |
| **Status** | Open — cut v0.7.1 ISO (no v0.7.0 overwrite); do not hotfix-loop |
| **Summary** | `sticklinkd` + `/etc/sticklink/sticklinkd.json` present on lab stick, but `sticklinkd --help` fails: `ModuleNotFoundError: No module named 'cryptography'`. Package list never included `python3-cryptography` / `python3-nacl` / `python3-websockets`. |
| **Notes** | Per product call: no in-place pip/hotfix chase — bake **v0.7.1** with those packages in `live-build/package-lists/stickllm.list.chroot`, flash, retry StickLink. |

**Security is parked** (2026-10-16). Do not implement NINO, firewalls, the client-stick lockdown, zero-trust remote access, pairing/TLS redesign, or signed updates until the working product is settled. The idea list and the checklist are one plan at the top of [FEATURES.md](FEATURES.md). **Next is ISS-021:** the same model filters on installed models, then the greyed Advanced controls. AMD / Intel GPU paths come after that. The rest of the vault story (stick key + PIN; not the duress PIN) comes after the GPU work.

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

### ISS-020 — Next ISO: drop baked Qwen2.5-7B Q5_K_M (keep ~2 GB 3B)
| | |
|---|---|
| **ID** | ISS-020 |
| **Mode** | all / build |
| **Severity** | PRODUCT (P0 next ship after v0.3.8) |
| **Status** | Done in v0.3.9. The 3B is baked; the 7B is download-only. Do **not** change the v0.3.8 or v0.3.9 ISOs |
| **Summary** | Next version: stop baking **Qwen2.5-7B Instruct Q5_K_M** (~5 GB split GGUF) into the ISO. Keep **Qwen2.5-3B Instruct Q4_K_M** (~2 GB) as the built-in test/default model. Users download 7B (and larger) via the hash-pinned catalog. |
| **Notes** | Touches when implementing (not now): `models/qwen2.5-7b-instruct-q5_k_m-*.gguf`, `scripts/download-model.sh`, `scripts/build.sh` + `scripts/lib/docker-build-live.sh` (`MODEL_SHARD*`), `config/models/catalog.toml` (`qwen25-7b-q5km` notes / bake wording — keep as **downloadable** pin), `config/profiles/amd-rtx3090.toml`, docs (`MODELS.md`, `BUILD.md`, `HARDWARE.md`). `overlay/etc/stickllm/default-model.env` already points at 3B. Leave shipping `out/v0.3.8/`, checksums, and Drive ISO alone. |

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
