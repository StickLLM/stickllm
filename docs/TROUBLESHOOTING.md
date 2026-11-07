# StickLLM troubleshooting

## Agent Zero: “127.0.0.1 refused to connect” on first open

**What you see:** After setup (or the first time you open Agent Zero), the Agent window shows Chromium’s **This site can’t be reached** / **127.0.0.1 refused to connect** (or localhost), instead of the Agent Zero chat UI.

**Why:** Agent Zero’s container takes a short time to answer after vault unlock / first start. An early open can leave the window on a dead loopback URL before the service is listening.

**What to do**
1. Prefer the **Starting… / Open Agent Zero** waiting panel — stay there until StickLLM swaps in the live Agent Zero page.
2. If you already see the refused-to-connect page: **Reload the desktop** (right-click the StickLLM desk → **Reload**, or press **F5**), then open **Agent Zero** again.

You should not need this after a Reload once Agent Zero has finished starting. Later StickLLM builds wait for Agent Zero’s API before embedding the page.

## Agent Zero apps open in a panel / don't open in a new tab

> **Applies to current versions.** This goes away once per-connection
> certificates land: StickLLM will then be reached through a server with a
> certificate issued per connection, so everything is HTTPS on one origin and
> there's only one site to allow.

**What you see:** you ask Agent Zero to open an app (for example "open
solitaire"). The app doesn't open in its own browser tab. It shows up in a
panel inside the StickLLM tab instead, or the StickLLM tab title flashes and
offers an **Open in new tab** button.

**Why:** Agent Zero opens the app from your StickLLM tab, but you didn't click
anything. Browsers block a new tab that opens without a click (a "pop-up")
unless you allow pop-ups for that site. StickLLM then falls back to the
in-tab panel so the agent can still use the app.

**http and https are different sites.** A browser treats the scheme, host and
port as one site. These are all separate entries in the pop-up list:

- `http://192.168.72.70` (the usual StickLLM tab on your network)
- `https://192.168.72.70`
- `https://192.168.72.70:5443` (the Agent Zero tab)

Allowing `https://192.168.72.70` does **not** allow `http://192.168.72.70`.
Allow the exact address shown in the address bar of the **StickLLM tab** (the
one with the desktop icons), not the Agent tab. If you use both http and
https, add both.

### Fix: allow pop-ups for the StickLLM address

Use the IP address your stick shows. `192.168.72.70` below is only an example.

**Chrome (Windows, macOS, Linux, Android)**
1. Open `chrome://settings/content/popups`.
2. Next to **Allowed to send pop-ups and use redirects**, click **Add**.
3. Type the exact StickLLM address, for example `http://192.168.72.70`, and click **Add**.
4. If you also open StickLLM over https, add `https://192.168.72.70` as well.
5. Reload the StickLLM tab (Ctrl+F5) and ask Agent Zero again.

Quick way: in the StickLLM tab, click the icon left of the address (the
padlock, or "Not secure") -> **Site settings** -> **Pop-ups and redirects** ->
**Allow**. Chrome also shows a blocked-pop-up icon at the right end of the
address bar; click it -> **Always allow pop-ups and redirects from ...**.

**Microsoft Edge**
1. Open `edge://settings/content/popups`.
2. Next to **Allow**, click **Add** and enter the exact address, for example `http://192.168.72.70`.
3. Reload the StickLLM tab.

**Firefox**
1. Open `about:preferences#privacy` and scroll to **Permissions**.
2. Next to **Block pop-up windows and third-party redirects**, click **Exceptions...**.
3. Enter the exact address, for example `http://192.168.72.70`, click **Allow**, then **Save Changes**.
4. Reload the StickLLM tab.

**Safari (macOS)**
1. With the StickLLM tab open, choose **Safari -> Settings -> Websites -> Pop-up Windows**.
2. Set the StickLLM address (for example `192.168.72.70`) to **Allow**.
3. Reload the StickLLM tab.

**iPhone / iPad (Safari and other iOS browsers)**
iOS has no per-site pop-up allow list. When Agent Zero opens an app, tap
**Open in new tab** once (in the StickLLM tab's panel, toast or
notification). You could turn off **Settings -> Safari -> Block Pop-ups**,
but that applies to every site, so the one tap is the recommended way.

### If you don't allow pop-ups

That's fine. The app loads in a panel inside the StickLLM tab and Agent Zero
can still read and play it. Switch to the StickLLM tab to watch, or click
**Open in new tab** to move it to its own tab.

### Still not working?

- Keep the StickLLM tab open. Agent Zero opens apps on the device that sent
  the chat, through that device's StickLLM tab.
- Reload the StickLLM tab with Ctrl+F5 after a StickLLM update.
- Only one paired device at a time is supported. If two devices both chatted
  with Agent Zero in the last 5 minutes, the most recent one gets the app.

## Microphone on the stick kiosk vs a remote phone/PC

**Kiosk (HDMI Chromium we own):** mic (and camera, if used) is auto-granted for
StickLLM loopback and this stick’s LAN/pair origins via Chromium enterprise
policy `AudioCaptureAllowedUrls` / `VideoCaptureAllowedUrls`
(`stickllm-media.json`, also written at kiosk start). There should be **no**
Allow prompt on the console. The kiosk user is also in the `audio` group so
`/dev/snd` capture devices are reachable.

**Remote LAN browser (phone/PC):** still normal browser rules — open the stick
over **HTTPS**, then **Allow** mic after a user gesture. StickLLM cannot push
kiosk policies into someone else’s Chrome/Safari.

## Microphone fails on a remote LAN browser

**What you see:** Agent Zero says something like "Failed to access microphone.
Please check permissions," or StickLLM toasts that the microphone needs HTTPS.
Windows Sound settings show the mic working.

**Why:** Chromium only allows `getUserMedia` in a [secure context](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts)
(`https://` or `http://localhost` / `127.0.0.1`). Plain `http://192.168.x.x/`
is not secure, so the browser blocks the mic even when the OS mic is fine.

### Fix

Use the stick IP from Settings → Devices (example `192.168.72.50`). Remote
`http://` page loads redirect to `https://` when TLS is up; the stick kiosk
(`http://127.0.0.1/`) stays on HTTP and uses the auto-grant policy above.

1. Open **`https://192.168.72.50/`** (or follow the redirect from `http://`).
2. In Chrome: **Advanced → Proceed to 192.168.72.50 (unsafe)** once so the
   self-signed stick certificate is trusted for this IP. (Or install the cert
   under Settings → Privacy → Security → Manage certificates.)
3. Pair this browser if prompted (code on the stick screen). HTTPS uses a
   separate pair cookie from plain HTTP — re-pair after switching.
4. Reload, open Chat / Agent Zero, and **Allow** the microphone when asked
   (padlock → Site settings → Microphone → Allow).

If the mic still fails after HTTPS + Allow: clear a prior Block for this IP
under `chrome://settings/content/microphone`, then retry.
