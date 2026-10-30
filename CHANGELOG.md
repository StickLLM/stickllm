# Changelog

## 0.5.5 (2026-10-30)

App agent
- Chat can drive ONLYOFFICE slides and Node-RED through the app agent
  (stickllm-appagent: request -> checked plan -> actions, with Undo). It uses a
  dedicated Qwen3.5-4B llama-server on 127.0.0.1:8796; the 4B Q4_K_M model is
  baked into the image at /opt/stickllm/models/appagent. The Qwen2.5-3B stays the
  default small chat model. ONLYOFFICE's Plugins tab is hidden.
- Node-RED: the agent never shadows the editor's own routes, reloads the open
  editor tab after a deploy and checks the real HTTP endpoint (hello world -> /hello).

Desktop
- New desktop layout (Auto/Desktop/Classic) with WinBox 0.2.82 windows, a start
  menu, taskbar and status tray; narrow windows keep the tabbed layout.
- Minesweeper starts as a game (solver overlay off); Files follows the StickLLM
  theme; Notepad's Back to Apps link tidied.

Models
- The baked Qwen3.5-4B shows as installed in Models, loads and chats, and cannot
  be deleted. Load works for Hugging Face hits already on disk; installed models
  sort first in search.
- Model probe no longer leaves "Recommended" blank on a machine with nvidia-smi
  but no GPU/driver.

Chat and vault
- A thinking model's reasoning is hidden (Show reasoning, collapsed).
- No more "No vault set up" / Ephemeral flash right after unlock, and the Vault
  tab no longer stays lit after lock. /api/health reports the USB settings as
  present-locked for a vault that is not yet bound.

## 0.5.4 (rc2, 2026-10-28)

Chat and vault (rc2)
- The Ephemeral/Vault tabs follow the vault: Ephemeral is highlighted whenever the
  vault is locked (first load included), Vault only after a successful unlock, and
  Ephemeral again on lock. /api/health reports "ephemeral" while the vault is locked.
- Lock (Ctrl+Shift+L, the lock buttons, switching to Ephemeral, or a lock from
  anywhere else seen by the status poll) clears the screen: transcript, chat list,
  saved-chat titles, drafts, attachments, in-memory history and the app tabs this
  page opened. Ephemeral chats are cleared too. Any reply in progress is stopped.

## 0.5.4 (rc1, 2026-10-28)

Apps
- Catalog shows each app's real name with its short tile name in a bright colour
  (for example **ONLYOFFICE** · Office, **Tasks.md** · Tasks, **Paisa** · Budget,
  **Trilium** · Notes), hidden apps included. ComfyUI and Node-RED keep their own names.
- Removed Radicale. Vikunja replaced by Tasks.md 3.3.0 (Markdown kanban, built once
  offline at install); Actual Budget replaced by Paisa v0.7.8. Old data folders are
  not migrated.
- Installing Tasks.md or Paisa no longer loops on "Pool overlaps": an unused
  network left by a retired app on the same subnet is removed first (only empty
  stickllm-* networks on that exact subnet).
- Trilium opens with no login (gateway pairing and the vault are the lock) and sets
  itself up automatically on first start.
- ComfyUI is installable. It uses the NVIDIA GPU when present (warns below 6 GB free
  VRAM) and otherwise runs on the CPU.

Office (ONLYOFFICE)
- New asks for a file name, defaulting to "Document/Spreadsheet/Presentation YYYY-MM-DD".
- Rename from the file list or from the editor title (open editors keep saving to the
  renamed file); Save copy as from the list or the editor's File menu.
- Downloads panel lists the vault Downloads folder with "Open in Office" (imports a copy).

Agent Zero
- Third-party plugins removed on every path, kiosk console included: empty allowlist
  enforced by the ISO build, plugin installer/scanner/validator deleted in the container,
  plugin badges removed. `verified.json` lists no plugins.
- Chat shows a friendly "No AI model is loaded yet" message instead of a connection
  error, in both the StickLLM chat and the Agent Zero chat.
- The llama relay no longer drops slow responses after 10 s (the connect timeout used
  to stay on the open socket).

System
- Missing AVX and low VRAM are warnings (Monitor card plus a one-time notice), not failures.
- Vault unlock: no brief "no vault set up" flash before the status loads; if the unlock
  form cannot be shown, an inline error says why. Switching to Vault mode on a locked
  vault asks for the passcode instead of saying "No vault yet".
- Text to speech falls back to a one-shot load when the resident voice cannot start.
- Build: `STICKLLM_OUT_DIR` may be an absolute path (for example `/e/stickllm-build/out`)
  so the ISO can be written to another local drive when C: is short on space.
