# Web mode (Internet / Tor / No internet)

StickLLM can steer **stick-local Chromium** — the HDMI kiosk browser and any
Browser window started by `stickllm-control` — through three modes:

| Mode | Tray colour | Effect on stick Chromium |
|---|---|---|
| **Internet** | Green | Direct uplink (normal browsing) |
| **Tor** | Yellow | Local Tor SOCKS; Chromium uses `socks5://127.0.0.1:9050` |
| **No internet** | Red | Chromium URL blocklist blocks the public web; loopback StickLLM still works |

Stick-origin fetches the gateway makes itself (optional web lookup / URL fetch)
follow the same mode: blocked in **No internet**, HTTP-tunneled through Tor in
**Tor**, direct in **Internet**.

## Remote LAN clients

Paired phones and PCs on the LAN keep **their own** network path. StickLLM cannot
force a remote browser through Tor or offline. The Settings / tray UI says so
when Web mode is open. Changing Web mode from a remote client still only
reconfigures the **stick’s** Chromium (and stick-origin fetches).

## Persistence and boot

- Desired mode is stored in `/var/lib/stickllm/web-mode.json`, and also on the
  USB settings partition (`/mnt/stickllm-settings/web-mode.json`) when that is
  mounted.
- `stickllm-web-mode.service` runs `stickllm-web-mode apply` at boot.
- Tor is **not** enabled at boot; `stickllm-web-mode` starts/stops `tor.service`
  only while mode is Tor.

## CLI

```bash
stickllm-web-mode status
stickllm-web-mode set internet|tor|none
stickllm-web-mode apply
```

Runtime JSON for the UI: `/run/stickllm/web-mode.json`.

## Test on the next bake

1. Boot the new image. Tray **Web** should show Internet (green).
2. Open Browser → `https://check.torproject.org` → not using Tor.
3. Tray **Web** → **Tor**. Wait until status says ready. Reload check.torproject.org → Tor.
4. Tray **Web** → **No internet**. Public sites fail; `http://127.0.0.1/` still works.
5. From a phone on the LAN: confirm the Web menu note that remote clients use
   their own network; phone browsing is unchanged by stick Tor / No internet.
