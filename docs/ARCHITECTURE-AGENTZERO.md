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
5. The target's newest StickLLM tab calls `window.open` for a named window `stickllm-<id>`. If the browser blocks the pop-up, a toast with an Open button appears instead.
6. The target's app page answers `app_state` and `app_act` when `window.stickllmApp` is present. The reply is `POST /api/ui/app-reply`; a reply from any other screen is refused (`404 unknown_req`).

**Which screen is the target.** The gateway remembers the LAN IP of the browser that last used Agent on `:5443` (`_AgentClients`). It counts as "driving Agent" while it has an Agent websocket open, or for `AGENT_TARGET_WINDOW` = 120 s after its last Agent request. Loopback is never recorded.
- If such a LAN browser exists, it is the target and the kiosk gets nothing (`reason=agent_lan`). If that browser has no StickLLM tab open, the event still goes only to it (`reason=no_ui_tab`); the app is never moved to the kiosk.
- Otherwise the kiosk is the target (`reason=no_lan_agent`).
- `kiosk.log` records it: `STICKLLM_OPEN_APP phase=published id=… subscribers=N target=<ip|kiosk> reason=…`, and `STICKLLM_APP phase=state|act id=… ok=… [error=…] target=…`.

**No hang when the app is not open.** App pages subscribe with `/api/ui/events?app=<id>` (`stickllm-bridge.js`). Before sending `app_state` or `app_act`, the gateway checks that the target has that app page open. If not, it answers at once with `409 {"error":"app_not_open","message":…}`, telling Agent Zero to call `open_app` first and, if nothing opened, to ask the user to allow pop-ups or click Open on the toast. There is no kiosk fallback, because that is exactly the bug this design fixes (the game showed up on the stick's screen while the user watched their own browser). If the page is open but does not answer, the call fails after 6 s with `error: "timeout"`.

On a LAN browser, allow pop-ups for the StickLLM address (for example `https://192.168.72.70`), or every open_app becomes a toast.

`window.stickllmApp` is `{ describe(), state(), act(action) }` and returns JSON. Minesweeper, Solitaire, Tetris, Notepad, and Calculator have adapters. Files, Media, and Monitor open with `open_app` only; `app_state` on them answers `no_adapter`. The Solitaire adapter matches each card to a pile by screen position, because the cards are children of `.cardTable`, not of `.pile`. An illegal Solitaire move is undone and returns `ok: false`.

The Tetris adapter wraps the vendored game's globals (`update`, `play`, `lose`) and leaves the game script unchanged. Agent Zero's first `app_act` switches Tetris to turn mode: gravity stops and the piece waits for the next action, so a slow local model can play one move at a time. `{"mode":"realtime"}` turns gravity back on, and a game started with the Space key is a normal real-time game. `{"place":{"col":c,"rot":r}}` rotates, shifts the piece so its leftmost cell is in column `c`, and hard-drops it in one call; `{"place":"suggested"}` uses `state.suggest`, a one-piece heuristic (height, lines, holes, bumpiness). `state` also has `board`, `view`, `current`, `next`, `rotations`, `score`, `lines`, and `status` (`ready`, `playing`, `paused`, `game_over`).

Agent Zero keeps the tool prompts of an old chat. After the app list changes, start a new chat.

Agent Zero tools are `open_app(id)`, `app_state(id)`, and `app_act(id, action)`. The skill is `/mnt/stickllm-settings/agent-zero/skills/stickllm-apps/SKILL.md`, mounted at `/a0/usr/skills/stickllm-apps/SKILL.md`. It says to use those tools, not the container's own browser, and to stop after 30 actions.

URL ids: `minesweeper`, `solitaire`, `tetris`, `notepad`, `calculator`, `files`, `media`, `monitor`. The desktop label minesweep is the id `minesweeper`.

## Vault

Unlock is the vault passcode. The same passcode opens the USB settings partition at `/mnt/stickllm-settings`. There is no second password. When `vault.key` and `vault-meta/recovery.sha256` already exist, those slots are added to the settings LUKS header as well: one key file and one recovery-phrase digest. Boot does not ask for the passcode. Chats and Agent Zero memory stay in the SSD vault (`/var/lib/stickllm/vault/addons/agent-zero`). Keys and Agent Zero settings stay on the settings partition.

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
