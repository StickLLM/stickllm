# Agent Zero plugin reviews (StickLLM 0.5.0)

Agent Zero plugins are Python and JavaScript that run inside the agent with
the agent's rights. Since 0.5.0 StickLLM does not let anyone install plugins at
runtime: no installer, no Plugin Hub, no ZIP/Git install, no delete. The only
third-party plugins that load are listed in
`overlay/usr/local/share/stickllm/agent-zero-plugins.allow`. Each entry is
pinned to one full commit SHA and a SHA256 over every file in the plugin.

## How it is enforced

| Layer | What happens |
| --- | --- |
| ISO build | `scripts/lib/a0_plugins.py bake` fetches each allowlisted repo at the pinned commit (shallow, no hooks, no submodules), checks `git rev-parse HEAD` equals the pin, checks the file-tree SHA256, copies it without `.git` to `/usr/local/share/stickllm/agent-zero-plugins/<name>`, and writes a `MANIFEST`. Any mismatch fails the build. Nothing is fetched at runtime. |
| Container start | `stickllm_agent.py assemble-plugins` rebuilds `vault/addons/agent-zero/plugins` from: our `stickllm_apps`, the baked allowlisted plugins (hash re-checked), settings-only files (`config.json`, `.toggle-*`) for built-in `_*` plugins, and empty mountpoints. It is mounted **read-only** at `/a0/usr/plugins`. |
| Old plugins | Anything else in the old writable `state/plugins`, `state/api` and `state/extensions` (all three are code paths Agent Zero loads) is moved to `vault/addons/agent-zero/quarantine/<time>/...` and logged by name in `quarantine/quarantine.log`. Nothing is deleted. |
| Code paths | `/a0/usr/api` and `/a0/usr/extensions` are empty read-only mounts. |
| Gateway (:5443) | 403 `plugins_locked` for `/api/plugins/_plugin_installer/*` (install_zip, install_git, update_plugin, fetch_index), `_plugin_scan`, `_plugin_validator`, the a0 connector plugin list, `/api/plugins` actions `delete_plugin` and `run_execute_script`, and the Plugin Hub / install UI pages. Paths are URL-decoded and `..`/`//` normalised first. |
| Skills | `a0-manage-plugin` and `a0-create-plugin` are removed inside the container before Agent Zero is copied into `/a0`. Upstream has no separate "contribute" skill; publishing is `a0-create-plugin/references/contribute.md`, so it goes with it. `_plugin_scan` is toggled off. |

To add a plugin: review it, add one line to the allowlist (name, repo, full SHA,
license, tree SHA256 from `python3 scripts/lib/a0_plugins.py tree-hash DIR`),
add a review below, rebuild the ISO.

### Known limits (residual)

- Global settings and on/off toggles of built-in plugins are read-only (saving
  fails with a read-only error). Per-project and per-agent settings still work.
- `_model_config` stays writable (settings partition, nested mount) because
  model choice must save. Only `config.json`, `presets.yaml` and `.toggle-*`
  may live there; anything else (for example a planted `plugin.yaml` that
  would replace the built-in plugin's code) is quarantined on every start.
- `_goal/goals` and `_orchestrator/data` are writable data folders. A plugin
  needs `plugin.yaml` at the read-only plugin root, so files there cannot
  become a plugin.
- `/a0/usr/agents/<profile>` (written by StickLLM for the apps prompt) can
  still hold agent-profile extensions and tools. Agent Zero's own code
  execution inside the container can also write anywhere in the container
  rootfs, which is recreated fresh on each start.
- The agent can reach `127.0.0.1:5099` from inside its own container without
  the gateway. Install calls from there still fail because the plugins folder
  is read-only.
- Next step (not done in 0.5.0): egress only while the Web toggle is on.

## Allowed

### clock_24h

- Repo: https://github.com/jphermans/a0-plugin-clock-24h
- Commit: `44842bc2fc0edb1e5bc4b777357ab9a4b5734ab0` (2026-04-13 14:11 EDT)
- Tree SHA256: `1e284abf0b075c542ff054bf7630ac887cb39942313525bd6bf6f2480590c94b`
- License: MIT (LICENSE file present)
- Size: 10 files, about 158 KB (most of it a 137 KB banner PNG in `docs/`).
- What runs: one 1.6 KB browser script,
  `extensions/webui/initFw_end/clock-24h.js`. It watches `#time-date` with a
  MutationObserver and rewrites it with the hours/minutes/seconds from
  `Date()` and `toLocaleDateString()`.
- No Python, no API handler, no tools, no `execute.py`/hooks, no network
  calls, no storage, no secrets. `index.yaml` holds Plugin Hub metadata with a
  GitHub screenshot URL; it is not loaded at runtime.
- `innerHTML` is built only from digits and the browser's own date string.
- `initFw_end` exists in Agent Zero v2.14 (`webui/js/initFw.js`).
- Risk: very low. Worst case the clock shows the wrong format.

### chat_status_marklet

- Repo: https://github.com/mbradaschia/a0-chat-status-marklet
- Commit: `7dce2643788b072ed7df1fe05b55e9e0e250e083` (2026-04-01 22:59 EDT)
- Tree SHA256: `f9676b7bb67bd336aeca3928cd298daf376d51f09e4ccdcd210103ab12ed8f8a`
- License: MIT (LICENSE file present)
- Size: 6 files, about 16 KB.
- What runs: `extensions/webui/sidebar-chats-list-end/marklet-init.html`
  (CSS plus a module import of its own store) and `webui/marklet-store.js`
  (9 KB). It wraps the sidebar `chatsStore.applyContexts` and `selectChat`
  (both exist in v2.14) to add a pulsing dot while a chat is running and an
  unread dot when it finished. State is a list of chat ids in
  `sessionStorage` only.
- Imports only Agent Zero's own `/js/AlpineStore.js` and
  `/components/sidebar/chats/chats-store.js`. No Python, no API handler, no
  network calls, no secrets.
- Risk: low. It monkeypatches two sidebar store functions; if a future Agent
  Zero changes them the dots stop working or the sidebar may misbehave. The
  Agent Zero image is pinned by digest, so this only matters when the pin
  moves; re-review then.

## Looked at, not allowed

| Plugin | Why not |
| --- | --- |
| chat_rename | Server-side Python API handler. |
| chat_sort_recent | Server-side Python helpers. |
| favorite_chats | Server-side Python and writes data into its own plugin folder (read-only now); no LICENSE file. |
| file_finder | Server-side Python API that walks the file system. |
| chat_status_lights | Server-side Python API; chat_status_marklet does the same job in the browser only. |
| eye_comfort | Needs to save its own settings into the plugin folder, which is read-only. |

The Plugin Hub index had 218 plugins on 2026-10-27; most add tools, API
handlers or network access and were not considered for "relatively safe".
