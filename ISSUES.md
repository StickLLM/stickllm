# StickLLM Issues Log

Lightweight product/bug log (same spirit as [FEATURES.md](FEATURES.md)). Not a GitHub Issues mirror.

**How to add an entry**
1. Pick the next `ISS-NNN` ID.
2. Put new open items at the top of **Open**.
3. Fill: ID, date, mode (Local / Term / Server / all), status, summary, notes/repro.
4. When fixed, move to **Closed** (or set status Closed) with a one-line resolution.

---

## Open

### Security / hardening

### ISS-006 — llama binds 0.0.0.0:8080 as root, no auth
| | |
|---|---|
| **ID** | ISS-006 |
| **Date** | 2026-10-11 |
| **Mode** | all |
| **Severity** | CRITICAL |
| **Status** | Open |
| **Summary** | `stickllm-llama.service` binds `--host 0.0.0.0` on port **8080** with **no auth** and runs as **root**, so anything on the LAN can reach the model and bypass pairing. |

**Notes**
- Pairing only gates the gateway/UI path; direct access to llama on `:8080` skips it.
- Service runs privileged while exposing an unauthenticated inference port on all interfaces.

**Ask**
- Bind to **127.0.0.1** only, and run the llama unit **unprivileged** (dedicated user).

---

### ISS-007 — Hardcoded stickllm password + SSH password login
| | |
|---|---|
| **ID** | ISS-007 |
| **Date** | 2026-10-11 |
| **Mode** | all |
| **Severity** | HIGH |
| **Status** | Open |
| **Summary** | Hardcoded `user:stickllm` with sudo, and SSH allows password login — anyone who knows the public password gets root. |

**Notes**
- Default credentials are fixed in the image; SSH password auth is enabled.
- Combined with sudo access, LAN/SSH exposure is full root compromise.

**Ask**
- Use a **random per-boot password**, or **SSH keys only** (disable password login).

---

### ISS-008 — sudoers.d/stickllm NOPASSWD is overly broad
| | |
|---|---|
| **ID** | ISS-008 |
| **Date** | 2026-10-11 |
| **Mode** | all |
| **Severity** | HIGH |
| **Status** | Open |
| **Summary** | `sudoers.d/stickllm` **NOPASSWD** allows any arguments, and is pointless while `stickllm` is also in the **sudo** group. |

**Notes**
- Broad NOPASSWD + group membership = passwordless root for the stickllm account.
- Does not meaningfully constrain what can be run via sudo.

**Ask**
- Tighten or remove the NOPASSWD drop-in; do not combine unrestricted NOPASSWD with sudo-group membership.

---

### ISS-009 — Gateway 0.0.0.0:80 pairing / token weaknesses
| | |
|---|---|
| **ID** | ISS-009 |
| **Date** | 2026-10-11 |
| **Mode** | all (Term / Server especially) |
| **Severity** | HIGH |
| **Status** | Open |
| **Summary** | Gateway binds **0.0.0.0:80**. Pairing uses a **6-digit code**, unsalted **SHA-256** compared with `!=`, **no attempt limit or expiry**, token stored in **plaintext** in `auth.json`, and **no CSP** header. |

**Notes**
- Small code space + no rate limit / expiry → brute-force friendly on the LAN.
- Unsalted hash compare and plaintext token on disk weaken the pairing story.
- Missing CSP leaves the web UI without a baseline content-security policy.

**Ask**
- Harden bind/auth: stronger pairing (or rate-limit + expiry), proper secret compare, stop plaintext token storage, add CSP; reconsider binding all interfaces if loopback/UI-only is enough.

---

### ISS-010 — Build cannot reproduce the working kiosk
| | |
|---|---|
| **ID** | ISS-010 |
| **Date** | 2026-10-11 |
| **Mode** | Local |
| **Severity** | HIGH |
| **Status** | Open |
| **Summary** | Build cannot reproduce the working kiosk: `docker-build-live.sh` writes its own **inline package list** and ignores `stickllm.list.chroot`; **cage**, **chromium**, **seatd**, and **libinput** are in **no** list; the kiosk script and unit are only installed by the **patch** scripts. |

**Notes**
- Declared package list (`live-build/package-lists/stickllm.list.chroot`) is not what the Docker build path actually installs.
- Critical Local/kiosk packages missing from any maintained list.
- Kiosk script + systemd unit live outside the normal overlay/hook install path (patch-ISO only).

**Ask**
- Make the live-build path the single source of truth: honor `stickllm.list.chroot` (or delete the inline list), package cage/chromium/seatd/libinput there, and install kiosk script/unit from overlay/hooks — not patch scripts.

---

### ISS-011 — stickllm-download-model only warns on missing sha256
| | |
|---|---|
| **ID** | ISS-011 |
| **Date** | 2026-10-11 |
| **Mode** | all |
| **Severity** | MEDIUM |
| **Status** | Open |
| **Summary** | `stickllm-download-model` only **warns** on a missing sha256; missing or mismatched hash should be fatal, and verified on the `.partial` file before `mv`. |

**Notes**
- Integrity check is optional in practice today.
- Moving an unverified download into place risks a bad/corrupt model becoming the active file.

**Ask**
- Make missing or mismatched sha256 **fatal**; verify hash on the `.partial` before `mv` into the final path.

---

### ISS-012 — stickllm-kiosk usermod + world-writable /run/stickllm
| | |
|---|---|
| **ID** | ISS-012 |
| **Date** | 2026-10-11 |
| **Mode** | Local |
| **Severity** | MEDIUM |
| **Status** | Open |
| **Summary** | `stickllm-kiosk` runs **usermod** at runtime and does `chmod 777 /run/stickllm` plus **666** on logs; pair files live there. |

**Notes**
- Runtime usermod is fragile and privilege-heavy for a kiosk boot path.
- World-writable runtime dir + loose log perms expose pair/session material under `/run/stickllm`.

**Ask**
- Use a dedicated **kiosk user created at build time**; tighten `/run/stickllm` and log permissions (no 777/666).

---

### ISS-013 — Chromium launched with --no-sandbox
| | |
|---|---|
| **ID** | ISS-013 |
| **Date** | 2026-10-11 |
| **Mode** | Local |
| **Severity** | MEDIUM |
| **Status** | Open |
| **Summary** | Chromium is launched with `--no-sandbox`. |

**Notes**
- Disables Chromium’s process sandbox on the Local kiosk browser.
- Raises impact of any renderer/compromise bug against the stick.

**Ask**
- Remove `--no-sandbox` (fix user/namespaces/permissions so the sandbox can work).

---

### ISS-014 — Hardcoded DRM/NVIDIA/threads/model/runtime/serial paths
| | |
|---|---|
| **ID** | ISS-014 |
| **Date** | 2026-10-11 |
| **Mode** | all |
| **Severity** | LOW |
| **Status** | Open |
| **Summary** | Hardcoded `/dev/dri/card0` (ASPEED BMC can be card0), `/dev/nvidia0-3`, `--threads 8`, a default **7B** path, `XDG_RUNTIME_DIR=/run/user/0`, and writes to `/dev/ttyS0`. |

**Notes**
- Wrong DRM card breaks display on BMC/IPMI hosts where card0 is ASPEED.
- Fixed NVIDIA device indices and thread count don’t match all SKUs.
- Root runtime dir and ttyS0 assumptions couple the product to one console layout.

**Ask**
- Detect DRM/GPU devices; make threads/model defaults profile-driven; avoid hardcoding `/run/user/0` and `/dev/ttyS0` where possible.

---

### ISS-015 — Build hook || true, chmod gaps, services, MOTD, hosts
| | |
|---|---|
| **ID** | ISS-015 |
| **Date** | 2026-10-11 |
| **Mode** | all |
| **Severity** | LOW |
| **Status** | Open |
| **Summary** | Build hook ends every command in `|| true`; chmod list incomplete; **control** and **usb** services not enabled; MOTD says **v0.1**; `/etc/hosts` appended without checking for an existing line. |

**Notes**
- `|| true` hides real setup failures in the chroot hook.
- Incomplete chmod leave permissions wrong on some installed paths.
- Missing enable for control/usb units; stale MOTD version; duplicate hosts lines possible on rebuild.

**Ask**
- Fail the hook on real errors; complete chmod coverage; enable control/usb; bump MOTD; idempotent `/etc/hosts` update.

---

### ISS-016 — Conflicting nvidia-drm modprobe confs
| | |
|---|---|
| **ID** | ISS-016 |
| **Date** | 2026-10-11 |
| **Mode** | all (GPU hosts) |
| **Severity** | LOW |
| **Status** | Open |
| **Summary** | Two conflicting **nvidia-drm** modprobe confs. Keep the one the **v0.2** ISO used. |

**Notes**
- Duplicate/conflicting `nvidia-drm` options can fight at boot.
- Shipping v0.2 behavior is the known-good reference (do not disturb golden artifacts).

**Ask**
- Keep a single modprobe conf matching the v0.2 ISO; remove the other.

---

### ISS-017 — Delete patch-iso scripts and weston/cog/pixman fallbacks
| | |
|---|---|
| **ID** | ISS-017 |
| **Date** | 2026-10-11 |
| **Mode** | Local |
| **Severity** | CLEANUP |
| **Status** | Open |
| **Summary** | Delete the **patch-iso** scripts and the **weston**, **cog**, and **pixman** fallback code once **ISS-010** (build/kiosk reproducibility) is fixed. |

**Notes**
- Patch scripts and compositor fallbacks exist because the normal build path cannot reproduce the working kiosk (see ISS-010).
- After ISS-010, this dead path is maintenance debt and confusion.

**Ask**
- After ISS-010 lands: remove patch-iso scripts and weston/cog/pixman fallback code.

---

### ISS-005 — Server console download progress/ETA stuck
| | |
|---|---|
| **ID** | ISS-005 |
| **Date** | 2026-10-11 |
| **Mode** | Server (maybe Term) |
| **Status** | Open |
| **Summary** | Model download ETA on Server console doesn’t continually update / feels stuck while a model downloads. |

**Notes / code peek**
- User: model download ETA on Server screen doesn’t continually refresh.
- `stickllm-bootstatus` `download_phase_msg` re-reads `download-progress.json` each poll (~3s) and builds a phase string with pct/bytes (`Downloading model… N% (…)`). Percent/bytes can refresh; the TIMER ETA path is separate.
- `format_eta_line` / `eta_budget_secs`: **not** speed- or bytes-based. For `Downloading*` it uses a **fixed soft budget of 600s**, then each paint computes `left = budget - phase_elapsed`.
- `ETA_PHASE` / `ETA_PHASE_START` reset whenever the **phase string changes**. Because the download phase string embeds percent/bytes, every progress tick can reset the ETA toward ~10m — so ETA looks stuck or jumps instead of smoothly counting down. Minute rounding (`ETA ~Nm left`) also makes small tick-down hard to see.
- Same bootstatus path serves Term; confirm there if needed. Related cadence: ISS-002 (~3s vs target ~10s).

**Ask**
- ETA should refresh continuously from real download progress (bytes/speed) or at least tick down without resetting on each percent string change; keep progress % updating on Server (and Term if same UX).

---

### ISS-003 — “API Key” naming/UX confusing on Server
| | |
|---|---|
| **ID** | ISS-003 |
| **Date** | 2026-10-11 |
| **Mode** | Server (also Term) |
| **Status** | Open |
| **Summary** | Labeling the pair token as **API Key** confuses users on Server console + Chat UI. |

**Notes**
- Console (`stickllm-bootstatus`) shows `API key:` / Bearer header after pair; Chat UI Models panel says “OpenAI-compatible… Use the pair token as a Bearer API key” plus “Copy API key”.
- Users may think it is a cloud vendor key, a permanent credential, or something separate from pairing — not an ephemeral session token from PAIR CODE.
- **ISS-004 decided:** next version removes/disables the external OpenAI-compatible LAN API. Follow-up: drop “API key” / Bearer copy UX and console hints aimed at third-party clients; pairing stays for StickLLM web if needed (pair token / session wording only).

**Ask**
- Prefer copy that ties the secret to pairing (“Pair token”, “Session Bearer”) over “API Key”; no third-party API story after next version.
---

### ISS-002 — Server console refresh rate too aggressive
| | |
|---|---|
| **ID** | ISS-002 |
| **Date** | 2026-10-11 |
| **Mode** | Server (also Term) |
| **Status** | Open |
| **Summary** | Server console/status screen refreshes too often; target ~every 10 seconds. |

**Notes / current interval**
- User feedback: screen refreshes too often; suggest ~10s.
- `overlay/usr/local/bin/stickllm-bootstatus`: main loop uses **`sleep 3`** while loading (`paint_loading` each pass) and **`sleep 3`** in the READY watch loop (full `draw_ready` only when IP/pair/UI/API/key signature changes; otherwise breadcrumb only).
- So poll/repaint cadence is **~3s** today (loading always clears/repaints; READY less often unless state flips). Target **~10s**.
- Chat UI `refreshStatus` is separate (`ui/app.js` ~8s) — this issue is the HDMI/console status screen.

**Ask**
- Lengthen bootstatus sleeps to ~10s (or make READY/loading intervals configurable); avoid full-screen clear/flicker when nothing changed.

---

### ISS-001 — Web lookup broken on Local
| | |
|---|---|
| **ID** | ISS-001 |
| **Date** | 2026-10-11 |
| **Mode** | Local |
| **Status** | Open |
| **Summary** | Chat UI **Web** checkbox does not yield live web results in Local (on-stick browser). |

**What “Web” is**
- UI toggle (`ui/index.html` / `ui/app.js`) sends `web: "on"|"off"` on `/v1/chat/completions`.
- Gateway (`overlay/usr/local/bin/stickllm-gateway`) does optional **DuckDuckGo HTML search** (`https://html.duckduckgo.com/html/`) plus a top-page fetch, then injects snippets into the model prompt (`stickllm_web` in the response).
- Not a Chromium browse tool; lookup is server-side from the stick.

**Notes / root-cause hint**
- Local does **not** intentionally disable the Web API: status still reports `web: true`; loopback skips pair only.
- Local boot path in `stickllm-bootstatus` **skips `ensure_network` / does not wait for LAN IP** before READY (UI + model are enough). Term/Server keep probing DHCP until an IP exists.
- `NetworkManager-wait-online` is masked; UI starts without network-online. On Local, NM may never be kicked the way Server/Term do.
- Likely failure mode: outbound HTTPS/DNS to DuckDuckGo fails (no default route / DNS yet, or never brought up) → gateway returns `search error` / empty-looking answers while the checkbox stays checked.
- Confirm on a Local session: `curl` to `html.duckduckgo.com` and `http://127.0.0.1/api/web/search?q=…` once chat is up; compare with Server/Term on the same host.
- **Related / dependency:** many hosts are WiFi-only; today StickLLM is Ethernet DHCP only (no credentials UI). WiFi setup (SSID + password) is now a **P0** in [FEATURES.md](FEATURES.md) under Client and networking — needed for Local Web / outbound internet when no wired link exists.

**Repro (expected)**
1. Boot menu → **Local**.
2. In on-stick chat UI, leave **Web** checked.
3. Ask something that needs live data (e.g. current price / “today”).
4. Observe no useful sources / no live facts (vs Term/Server with network).

---

## Closed

### ISS-004 — Decide whether to keep/expose LAN OpenAI API
| | |
|---|---|
| **ID** | ISS-004 |
| **Date** | 2026-10-11 |
| **Mode** | Server (also Term) |
| **Status** | Decided / Closed (for next version) |
| **Summary** | **Do not ship** an OpenAI-compatible LAN API for external clients next version; privacy path = StickLLM-controlled UI only (Local + Server/Term web). |

**Decision**
- Next version: remove/disable the OpenAI-compatible LAN API surface for uncontrolled clients. No code rip-out in the current flash until that version ships.
- Pairing may remain for the StickLLM web client if needed; it is not an invitation for third-party OpenAI clients.
- User rationale (2026-10-11): *“kill API. It locks things down to what we can control. I can't control external clients.”*

**Resolution**
- Product go/no-go closed: prefer StickLLM UI only; see [FEATURES.md](FEATURES.md) (API item marked removed next version) and [README.md](README.md) (current flash still has the endpoint; deprecated for next version).
