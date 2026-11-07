# Web mode (Internet / Tor / No internet)

StickLLM steers **stick Browser windows** (opened from the desktop Browser app via
`stickllm-control`) and stick-origin gateway fetches. The HDMI **StickLLM desktop /
Settings / Wi-Fi** stay on the normal uplink so Tor cannot trap networking UI.

| Mode | Tray colour | Effect |
|---|---|---|
| **Internet** | Green | Browser windows + stick-origin fetches use the normal uplink |
| **Tor** | Yellow | Chromium PAC: public sites → `SOCKS5 127.0.0.1:9050`; loopback/LAN (Settings / Wi-Fi) → `DIRECT` |
| **No internet** | Red | Chromium URL blocklist blocks the public web; StickLLM on loopback **and** private LAN still works |

Toggling Tor **closes** open Browser windows; open Browser again so the new
window gets SOCKS (or direct). `tor_ready` is only true after StickLLM fetches
`https://check.torproject.org/api/ip` **through Tor** and sees `"IsTor": true`.

Stick-origin fetches the gateway makes itself (optional web lookup / URL fetch)
follow the same mode: blocked in **No internet**, HTTP-tunneled through Tor in
**Tor**, direct in **Internet**.

## Remote LAN clients

Paired phones and PCs on the LAN keep **their own** network path. StickLLM cannot
force a remote browser through Tor, offline, or Incognito. The Settings / tray UI
says so when Web mode is open. Changing Web mode from a remote client still only
reconfigures the **stick’s** Chromium (and stick-origin fetches).

Opening **Browser** from a remote client opens a new tab to `/browser-home.html`
(not `about:blank`). That page:

- Labels **Remote web client** vs **StickLLM USB Stick**
- Shows stick **Agent Zero: Tor** / **Agent Zero: No internet** / Internet clearly
- Notes that in Tor mode, **Agent Zero and other StickLLM applications on the USB
  Stick** use Tor even when you are driving the stick from a remote client
- Shows stick Ephemeral / Vault
- Callout: Tor / Incognito for *this remote tab* are not applied by StickLLM —
  install Tor / enable Incognito on the workstation yourself. Stick Desktop
  Browser Incognito still applies only on the StickLLM USB Stick.

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

If the stick browser is stuck in Tor (cannot leave / cannot scan Wi-Fi), from a
phone on the LAN or a TTY:

```bash
sudo stickllm-web-mode set internet
```

That writes a direct Chromium policy and stops Tor. Mode changes do **not**
restart the kiosk or kill Chromium (that blanked HDMI and broke mid model-load).
If a Browser window still looks stuck on Tor, use Reload desktop. Runtime JSON:
`/run/stickllm/web-mode.json`.

## Tor vs Wi-Fi

Managed `ProxyMode=direct` **overrides** Chromium `--proxy-server`, so Tor mode
uses a **PAC** instead: loopback + RFC1918 → `DIRECT` (Settings / Wi-Fi); all
other hosts → `SOCKS5 127.0.0.1:9050`. Re-open Browser after toggling Tor so the
new process loads the PAC. `tor_ready` requires check.torproject `"IsTor": true`
through Tor. Model load / llama are untouched by Web mode.

## Browser home and Ephemeral / Incognito

Desktop **Browser** opens `http://127.0.0.1/browser-home.html` (local file under
`/opt/stickllm/ui/`). It shows the StickLLM banner plus:

- **Session mode** — Ephemeral or Vault (`session_mode` from `GET /api/web-mode`)
- **Privacy** — Incognito when Ephemeral; normal browsing when Vault
- **Web mode** — Internet / Tor / No internet

When session mode is **Ephemeral**, `stickllm-control` starts Desktop Browser
windows with Chromium `--incognito` (history and cookies are not kept). Vault
mode uses a normal profile for that window. Switching Ephemeral ↔ Vault closes
open Desktop Browser windows so the next open matches the new policy. The HDMI
StickLLM kiosk is never launched Incognito.

## Test on the next bake

1. Boot the new image. Tray **Web** should show Internet (green).
2. Open Browser → home page shows StickLLM + **Internet**; then try `https://check.torproject.org` → not using Tor.
3. Tray **Web** → **Tor**. Wait until ready. **Close and reopen Browser** → home shows Tor; check.torproject.org → Tor.
4. While in Tor: Settings → Network Wi-Fi scan still works; switch back to **Internet**.
5. Tray **Web** → **No internet**. Re-open Browser → home shows No internet; public sites fail; StickLLM UI still works.
6. From a phone on the LAN: remote browsing is unchanged by stick Tor / No internet.
