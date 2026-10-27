# Agent Zero on StickLLM

The `stickllm-agentzero` branch runs Agent Zero beside StickLLM. The image is not inside the ISO. A person installs it from the Apps catalog, which runs `stickllm-agent install`. Chat stays on the StickLLM page. Agent Zero has its own tab.

## Components

| Piece | Where |
|---|---|
| Gateway | `overlay/usr/local/bin/stickllm-gateway` |
| Agent launcher | `overlay/usr/local/bin/stickllm-agent` |
| Agent library | `overlay/usr/local/lib/stickllm_agent.py` |
| Catalog installs | `overlay/usr/local/lib/stickllm_apps.py` |
| Console browser | `stickllm-kiosk`, Chromium as user `stickllm` |
| Container | `stickllm-agent-zero` on bridge `stickllm-a0` (`172.30.0.0/24`) |

The container has `no-new-privileges` and `NVIDIA_VISIBLE_DEVICES=void`. It does not take GPU memory from llama. Host is `172.30.0.1`. The container is `172.30.0.2`. nftables allows that bridge to reach only `172.30.0.1` tcp `8080`, `8081`, and `8082`.

## Units

`stickllm-agent.service` owns `dockerd`, the bridges, and the container (`stickllm-agent run`). It is enabled, but skipped at boot until the vault is mounted. Unlock runs `stickllm-agent start`, which is `systemctl start stickllm-agent.service`. The Apps page install runs `systemctl start --no-block stickllm-agent-install.service` (oneshot `stickllm-agent install`). After the smoke test the installer stops any `dockerd` it started and runs `systemctl restart stickllm-agent.service`. Nothing Agent Zero needs stays in the `stickllm-ui` cgroup, so restarting the UI (the vault unlock does this) leaves Agent Zero running, and `systemctl status stickllm-agent` shows it. The gateway falls back to running `stickllm-agent install` directly only when `systemctl` fails.

## Ports

| Port | Who |
|---|---|
| `http://127.0.0.1/` | Kiosk and the local StickLLM UI |
| `:80` and `:443` | Gateway. Paired browsers use `https://<stick>/` |
| `127.0.0.1:5099` | Agent Zero UI, loopback only |
| `:5443` | Paired TLS proxy to `127.0.0.1:5099`. Not a path under `/agent` |
| `127.0.0.1:8080` | llama-server |
| `172.30.0.1:8080` | Llama relay for the container |
| `172.30.0.1:8081` | Read-only copy of StickLLM apps for Agent Zero |
| `127.0.0.1:8082` and `172.30.0.1:8082` | open_app control. Not bound on `0.0.0.0` |

The kiosk opens StickLLM at `http://127.0.0.1/` and opens an app window itself. A paired browser on the LAN uses `:443`. EventSource cannot send the pair header, so `/api/ui/events` accepts the pair cookie or a short-lived `?t=` ticket from `POST /api/ui/events-ticket`. The long-lived pair token is never put in a URL.

## open_app

1. Agent Zero calls `open_app`, `app_state`, or `app_act`.
2. Those tools post to `http://172.30.0.1:8082` with the open-app token (`/stickllm-open-app.token`, file `/mnt/stickllm-settings/agent-zero/open-app.token`).
3. The bridge notifies the gateway.
4. The gateway `_UiOpenBus` publishes on `SSE /api/ui/events`, but only to one screen, the target (see below).
5. Kiosk and LAN browser do exactly what a click on the app's desktop icon does: the StickLLM tab calls `window.open(icon.href, icon.target)`, i.e. `/apps/<id>/` with the named target `stickllm-<id>` and no window features, so the browser opens a new tab or reuses that app's tab (result `opened`). The kiosk policy allows pop-ups for `http://127.0.0.1`, so the kiosk always opens at once; a LAN browser opens at once only if the user allowed pop-ups for StickLLM. Otherwise a toast with an "Open in new tab" button (and, for a background tab, a title flash and a notification if allowed) offers one click that runs that same open (result `toast-shown`). Only if the browser refuses the tab even on that click does the app open in an in-page panel inside the StickLLM tab (iframe named `stickllm-embed-<id>`, result `embedded`): a last resort so the agent can still play. The panel's "Open in new tab" button opens the tab and the panel closes when that tab's app page connects (BroadcastChannel `stickllm-apps`, `tab-ready`). The iframe must never share the tab's name: Chrome resolves a named target to a same-named iframe first, which is why "Open in window" used to navigate the iframe and then remove it (the app "vanished"). App page auth on a LAN browser: the paired tab POSTs `/api/ui/apps-session` (Bearer, `X-StickLLM-Client: ui`; on pairing, on becoming visible, on pointerdown on a desk icon, at most every 5 min) and gets the HttpOnly `stickllm_apps` cookie (SameSite=Strict, Secure on https; derived from the pairing, so a remint kills it). Loopback answers `{"ok":true,"cookie":false}` because the kiosk needs no auth. That cookie opens `/apps/*`, `/api/ui/events?app=` and `/api/ui/app-reply` only, and replaces reliance on the script-set `stickllm_pair` cookie, which every StickLLM tab on the host shares and can clear or overwrite. No ticket is put in the URL, so the agent open and the icon click use the identical URL. Without a pairing, `/apps/*` stays 401 `pair_required`; kiosk.log logs `STICKLLM_APPS_AUTH` lines (session=set/refused, denied; cookie state only, never values). `/apps/*` pages send `frame-ancestors 'self'`; every other page keeps `frame-ancestors 'none'`.
6. The target's app page answers `app_state` and `app_act` when `window.stickllmApp` is present. The reply is `POST /api/ui/app-reply`; a reply from any other screen is refused (`404 unknown_req`).

**Which screen is the target.** The gateway remembers the device that last sent Agent a chat message on `:5443` (`POST /api/message_async`, which is what Agent Zero's web UI sends; the bare `/message_async` and `/message` are older builds; `_AgentClients.prompt`, logged as `STICKLLM_AGENT_PROMPT ip=… screen=… path=…`). A device is its `stickllm_device` cookie: a random, non-secret id that every StickLLM tab sets (`ensureDeviceCookie` in app.js). Cookies are per host, not per port, so the same browser's Agent tab on `:5443` sends it too. This makes it work for any paired device (phone, iPad, laptop, desktop), even several behind one NAT IP or a phone that changes IP. A browser without the cookie falls back to its IP, and logs show `target=device:<first 8 hex>` or the IP. The id only routes events; every stream and reply still needs the pairing. There is one pairing at a time today, so all devices share it; per-device pairings would be a later change. On iOS and other browsers that block pop-ups, the app opens through the toast's one-tap "Open in new tab". It counts as "driving Agent" for `AGENT_TARGET_WINDOW` = 300 s after that message. An open Agent tab that only polls or holds a websocket does not count: the kiosk's own Agent window talks to `127.0.0.1:5099` directly and is invisible to the gateway, so with the old rule (any Agent traffic in 120 s or an open websocket) a forgotten Agent tab on the PC captured every open_app and the kiosk never got one. Loopback is never recorded. If both screens chatted within 5 minutes, the LAN browser wins. `app_state`/`app_act` go to the screen the app was opened on while its page is still open, else to the current target.
- If such a LAN browser exists, it is the target and the kiosk gets nothing (`reason=agent_lan`). If that browser has no StickLLM tab open, the event still goes only to it (`reason=no_ui_tab`); the app is never moved to the kiosk.
- Otherwise the kiosk is the target (`reason=no_lan_agent`).
- `kiosk.log` records it: `STICKLLM_OPEN_APP phase=published id=… subscribers=N target=<ip|kiosk> reason=…`, and `STICKLLM_APP phase=state|act id=… ok=… [error=…] target=…`.

**No hang when the app is not open.** App pages subscribe with `/api/ui/events?app=<id>` (`stickllm-bridge.js`). Before sending `app_state` or `app_act`, the gateway checks that the target has that app page open. If not, it answers at once with `409 {"error":"app_not_open","message":…}`, telling Agent Zero to call `open_app` first and, if nothing opened, to ask the user to keep a StickLLM tab open and reload it. There is no kiosk fallback, because that is exactly the bug this design fixes (the game showed up on the stick's screen while the user watched their own browser). If the page is open but does not answer, the call fails after 6 s with `error: "timeout"`.

On a LAN browser, keep a StickLLM tab (for example `https://192.168.72.70`) open. Allowing pop-ups for the stick makes agent opens instant; otherwise click "Open in new tab" once in the toast or notification. App tabs are named `stickllm-<id>` (the panel iframe `stickllm-embed-<id>`), so `stickllm-bridge.js` answers `app_state`/`app_act` even while that tab is hidden. Closing the app tab or panel ends its page, and the next app call returns `app_not_open`.

`window.stickllmApp` is `{ describe(), state(), act(action) }` and returns JSON. Minesweeper, Solitaire, Tetris, Notepad, and Calculator have adapters. Files, Media, and Monitor open with `open_app` only; `app_state` on them answers `no_adapter`. The Solitaire adapter matches each card to a pile by screen position, because the cards are children of `.cardTable`, not of `.pile`. An illegal Solitaire move is undone and returns `ok: false`.

The Tetris adapter wraps the vendored game's globals (`update`, `play`, `lose`) and leaves the game script unchanged. Agent Zero's first `app_act` switches Tetris to turn mode: gravity stops and the piece waits for the next action, so a slow local model can play one move at a time. `{"mode":"realtime"}` turns gravity back on, and a game started with the Space key is a normal real-time game. `{"place":{"col":c,"rot":r}}` rotates, shifts the piece so its leftmost cell is in column `c`, and hard-drops it in one call; `{"place":"suggested"}` uses `state.suggest`, a one-piece heuristic (height, lines, holes, bumpiness). `state` also has `board`, `view`, `current`, `next`, `rotations`, `score`, `lines`, and `status` (`ready`, `playing`, `paused`, `game_over`).

Agent Zero keeps the tool prompts of an old chat. After the app list changes, start a new chat.

Agent Zero tools are `open_app(id)`, `app_state(id)`, and `app_act(id, action)`. The skill is `/mnt/stickllm-settings/agent-zero/skills/stickllm-apps/SKILL.md`, mounted at `/a0/usr/skills/stickllm-apps/SKILL.md`. It says to use those tools, not the container's own browser, and to stop after 30 actions.

URL ids: `minesweeper`, `solitaire`, `tetris`, `notepad`, `calculator`, `files`, `media`, `monitor`. The desktop label minesweep is the id `minesweeper`.

## Vault

Unlock is the vault passcode. The same passcode opens the USB settings partition at `/mnt/stickllm-settings`. There is no second password. When `vault.key` and `vault-meta/recovery.sha256` already exist, those slots are added to the settings LUKS header as well: one key file and one recovery-phrase digest. Boot does not ask for the passcode. Chats and Agent Zero memory stay in the SSD vault (`/var/lib/stickllm/vault/addons/agent-zero`). Keys and Agent Zero settings stay on the settings partition.

Known gap (v0.4): Docker's own container log is not in the vault. No `--log-driver` is set, so Agent Zero's stdout goes to `json-file` under `<data-root>/containers/` on the plain host SSD, and anything written outside the mounted folders stays in the container's writable layer there. `/tmp` is a RAM disk (tmpfs). The fix is queued for the next version: `--log-driver none` and a read-only container.

## Disk

Docker data-root is the host SSD folder beside the models directory (`<models parent>/stickllm-docker`). `dockerd` is not the system `docker.service`. Its log is `/run/stickllm/agent-dockerd.log` and a copy that survives reboot at `<data-root parent>/stickllm-logs/agent-dockerd.log`.

`stickllm-agent` runs `dockerd` in the host mount namespace (PID 1's). The Apps page install is started by `stickllm-gateway`, and `stickllm-ui` has a private mount namespace (`ProtectSystem=full`, `ProtectHome=true`). `dockerd` mounts each container rootfs itself, while the system `containerd` and `runc` run in the host namespace. A `dockerd` started inside the gateway namespace pulls fine, but every container gets an empty rootfs (`stat /bin/sh: no such file or directory`, `reading from a closed fifo`). `stickllm-agent` therefore re-execs itself with `nsenter --mount=/proc/1/ns/mnt`, and restarts a `dockerd` it finds in another mount namespace.

The data-root path length is not the limit. mount(2) reads at most one 4096-byte page of options, but overlay2 passes the short `l/<id>` links (about 3.2 KB for the 23-layer image under `.../home/<user>/.lmstudio/stickllm-docker`) and falls back to relative paths past one page. `docker inspect` shows full `diff` paths in `LowerDir` (4242 bytes here), which is not the mount string.

Background daemons close fd 9 (`9>&-`), so `dockerd` and the bridges never keep `/run/stickllm/agent-install.lock`. A leaked lock made every later install exit at once with `install already running`.

The older layout `/var/lib/stickllm/vault/docker` (commit `3db2ac0`) is not detected. The image is re-pulled onto the host SSD. Do not point dockerd back at the vault.

Catalog installs do not use `/var/lib/stickllm/apps`. That path is the live overlay and is wiped at reboot. `persistent_install_root()` writes, in order:

1. The host SSD apps folder beside the recorded models directory.
2. The USB DATA partition, `/mnt/stickllm-data/apps`, with the record at `/mnt/stickllm-data/apps-installed.json`.
3. The unlocked vault, `/var/lib/stickllm/vault/apps`.

`:8081` serves the StickLLM app pages to Agent Zero only. It is not the catalog install directory.

The installer pulls the pinned Agent Zero image and smoke-tests `/bin/sh` for `/bin/bash` and `/usr/bin/python3` before it starts the container. The previous image id is tagged `stickllm-agent-zero:rollback` and is not deleted.

### open_app without a click (2026-10-26, openapp6)

A Agent Zero open_app reaches the StickLLM tab of the device that chatted
(device cookie). With no user gesture, Chrome refuses `window.open` unless
pop-ups are allowed for the StickLLM site. The user is normally on the Agent
tab, so a toast in the StickLLM tab alone left the agent with no app page
(`app_state` -> `app_not_open`). Now, when the tab is refused, the app loads in
the in-page panel (`stickllm-embed-<id>`) so the agent can play at once, the
StickLLM tab title flashes, and "Open in new tab" moves it to a real tab on one
click. Allowing pop-ups for the StickLLM site makes it open as a tab directly.
iOS Safari: same panel + one-tap button.

### Pop-up permission is per origin (resolved 2026-10-26)

The last desktop failure on 2026-10-26 was a browser setting, not code. Pop-ups
were allowed for `https://192.168.72.70`, but the StickLLM tab that calls
`window.open` is on `http://192.168.72.70`. Chrome keys site permissions by
origin (scheme + host + port), so the https allow didn't apply and every
no-click `open_app` was refused. After Nink allowed `http://192.168.72.70`
(22:45 EDT), Solitaire opened in its own tab. The permission that matters is
the one for the **StickLLM UI origin**, never the Agent tab (`:5443`). User
steps: [TROUBLESHOOTING.md](TROUBLESHOOTING.md#agent-zero-apps-open-in-a-panel--dont-open-in-a-new-tab).
Commits: `c4640f9` (desktop-icon click path, apps cookie, chat-based target),
`488e0ac` (`/api/message_async` counted, `stickllm_device` cookie target),
`5e4618c` (in-page panel when the tab is refused, openapp6).
Temporary: the planned server connection with per-connection certificates
(everything HTTPS on one origin) removes the http/https split.

