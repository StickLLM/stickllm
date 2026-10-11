# StickLLM Issues Log

Lightweight product/bug log (same spirit as [FEATURES.md](FEATURES.md)). Not a GitHub Issues mirror.

**How to add an entry**
1. Pick the next `ISS-NNN` ID.
2. Put new open items at the top of **Open**.
3. Fill: ID, date, mode (Local / Term / Server / all), status, summary, notes/repro.
4. When fixed, move to **Closed** (or set status Closed) with a one-line resolution.

---

## Open

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
| **Summary** | Server console/status screen refreshes too often; target ~every 5 seconds. |

**Notes / current interval**
- User feedback: screen refreshes too often; suggest ~5s.
- `overlay/usr/local/bin/stickllm-bootstatus`: main loop uses **`sleep 3`** while loading (`paint_loading` each pass) and **`sleep 3`** in the READY watch loop (full `draw_ready` only when IP/pair/UI/API/key signature changes; otherwise breadcrumb only).
- So poll/repaint cadence is **~3s** today (loading always clears/repaints; READY less often unless state flips). Target **~5s**.
- Chat UI `refreshStatus` is separate (`ui/app.js` ~8s) — this issue is the HDMI/console status screen.

**Ask**
- Lengthen bootstatus sleeps to ~5s (or make READY/loading intervals configurable); avoid full-screen clear/flicker when nothing changed.

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
