# StickLLM Issues Log

Lightweight product/bug log (same spirit as [FEATURES.md](FEATURES.md)). Not a GitHub Issues mirror.

**How to add an entry**
1. Pick the next `ISS-NNN` ID.
2. Put new open items at the top of **Open**.
3. Fill: ID, date, mode (Local / Term / Server / all), status, summary, notes/repro.
4. When fixed, move to **Closed** (or set status Closed) with a one-line resolution.

---

## Open

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
