# StickLLM Issues Log

Lightweight product/bug log (same spirit as [FEATURES.md](FEATURES.md)). Not a GitHub Issues mirror.

**How to add an entry**
1. Pick the next `ISS-NNN` ID.
2. Put new open items at the top of **Open**.
3. Fill: ID, date, mode (Local / Term / Server / all), status, summary, notes/repro.
4. When fixed, move to **Closed** (or set status Closed) with a one-line resolution.

---

## Open

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

_(none yet)_
