# Desktop (windowed) layout — plan

Branch `feature/desktop-ui` (from `feature/app-agent` 9473ba7). Local commits only.

## Goal

On a desktop browser (kiosk screen or a paired LAN PC) the web UI becomes a small
desktop: movable, resizable windows with minimise / maximise / restore / close,
a start-menu launcher, a taskbar of open windows, a clear active window, and the
existing vault, network and model status in a taskbar tray. Phones and tablets
keep today's layout unchanged. First pass covers the bundled starter apps only
(Files, Notepad, Calculator, Minesweeper, Solitaire, Tetris, Media, System
monitor). Catalog add-ons, ONLYOFFICE, Node-RED, Agent Zero keep opening in
their own named tab exactly as now.

## Detection

`ui/desktop-core.js` → `detectLayout({pointerFine, hover, width, height, override})`

- Auto: desktop when `(pointer:fine)` and `(hover:hover)` match and the
  viewport is at least 1024 × 600 CSS px. Anything else (touch, narrow) is
  classic. A 1024 px tablet with a touch pointer stays classic.
- Override per device in `localStorage["stickllm.uiLayout"]` =
  `auto | desktop | classic`. Set from Settings → General → *Layout*, and from
  the launcher (*Switch to classic layout*). localStorage is per browser, so
  the kiosk and each LAN PC choose independently.
- Re-evaluated on resize / pointer changes (debounced); switching tears the
  desktop down and puts every moved node back where it was.
- Classic/mobile never loads WinBox (the script is injected only when the
  desktop layout starts), so the mobile payload and DOM are unchanged.

## Window manager

- WinBox.js 0.2.82, vendored at `ui/vendor/winbox-0.2.82/` (see
  `VENDOR.txt`, `THIRD_PARTY_NOTICES.md`). No CDN.
- `desktop-core.js` (pure, Node-testable): layout detection, geometry
  clamp/cascade, persistence, taskbar click rule, and a `WindowManager` that
  drives any WinBox-like factory (a fake in tests).
- `desktop.js` (DOM): desktop layer, taskbar, launcher, tray, hooks.
- Windows live in a `#deskLayer` stacking context (z-index 1), so WinBox's
  ever-growing z-index never climbs over Settings, dialogs, toasts, the load
  bar or the context menu.
- Minimise hides the window (no WinBox mini-bars); the taskbar button is the
  way back. Maximise fills the area above the taskbar. Double-click title
  toggles maximise. Windows are kept inside the viewport on browser resize.
- Taskbar button click: minimised → restore + focus; visible but not active →
  focus; active → minimise.
- Active window: accent title bar + accent ring/shadow; inactive windows get a
  muted title bar and slightly dimmed content. Taskbar marks the active app
  (accent underline) and minimised apps (dimmed).

### iframe vs DOM mount

- Starter apps: same-origin `<iframe src="/apps/<id>/" name="stickllm-<id>">`.
  They are full pages with their own CSS/JS, so an iframe isolates them; the
  name keeps the app bridge (Agent Zero `app_state` / `app_act`) working
  because the bridge already treats `stickllm-<id>` as a named app. One window
  per app (same rule as one tab per app).
- Chat: the existing `#app` DOM is mounted into a *Chat* window (not an
  iframe — it is the same page, keeps all state and event handlers).
  Overlay nodes inside `#app` (Settings and other dialogs, load bar, toast)
  are moved to `<body>` first, because WinBox windows use CSS containment and
  would trap fixed-position overlays inside the window. Closing the Chat
  window minimises it (it is the shell; it can't go away). It is pinned first
  on the taskbar.
- Why a window and not a pinned side panel: it can be moved, tiled next to an
  app or maximised for long chats, and uses the same controls as everything
  else; a panel would take fixed width from every app.

### Launcher

Start button (bottom-left) / `Ctrl+Alt+Space` (or the Windows-style Meta key
on its own is avoided: the kiosk compositor may grab it). Lists Chat and the
bundled apps (from the existing `#deskIcons a[data-starter]`, so names/icons
stay in one place), then *Apps & installs* (the existing Apps page inside the
Chat window, add-ons still open as tabs), Settings, Lock vault (when open),
*Switch to classic layout*. Type-to-filter; Enter opens the first match; Esc
closes. The desktop background shows the same app icons (double-click opens).

### Tray

The existing nodes move, so every existing updater keeps working:
- Model: `#statusChip` + `#statusPop` move into the tray (popover opens
  upward).
- Network: a new tray icon mirrors `#popUplink` (Online / No uplink) via a
  MutationObserver; click opens Settings → Network.
- Vault: a new tray icon mirrors `#popVault` (Unlocked / Locked / Not set up);
  click locks when unlocked, otherwise opens Settings → Storage & Vault.
- Pairing link, theme toggle, clock.
Leaving the desktop layout puts every node back in its original place.

## State persistence

`localStorage["stickllm.desk.v1"]` = `{ geom: { <appId|chat>: {x,y,w,h,max} } }`
saved on move/resize/maximise (debounced). Positions only: windows are not
re-opened after a reload, because app windows can show vault data and Lock
must leave nothing on screen. Out-of-range saved geometry is clamped to the
current screen.

## Keyboard

- `Ctrl+Shift+L` lock: unchanged handler. `clearOnLock()` now also closes every
  app window and minimises nothing — chat is cleared as before (new chat,
  empty list/drafts). Key events inside app iframes don't reach the parent,
  so desktop.js forwards `Ctrl+Shift+L`, `F9`, `F10` and the desktop
  shortcuts from each same-origin app iframe to the main window.
- `Ctrl+Alt+Space` launcher · `Esc` closes launcher · `Ctrl+Alt+W` close
  window · `Ctrl+Alt+M` minimise · `Ctrl+Alt+Up` maximise/restore ·
  `Ctrl+Alt+N` next window · `Ctrl+Alt+C` chat. Ctrl+Alt avoids clashing with
  browser and app shortcuts (Ctrl+W, Alt+F4 are the browser's).
- Listed in Settings → General → Keyboard shortcuts.

## Hooks in app.js (minimal)

- `openAppPaired` / `openAppTab`: if `window.stickDesk.handles(id)` (desktop
  layout + starter app) open a window instead of a tab. That also makes
  Agent Zero `open_app` open a window with no pop-up permission needed.
- `clearOnLock`: `window.stickDesk.closeAll()`.
- Settings → General: Layout row (`#layoutSeg`), wired by desktop.js.
- app.js is one IIFE, so it publishes `window.stickApp` (`openSettings`,
  `lockVault`, `showApps`, `toast`) for the start menu and tray buttons.

## Tests

- `tests/desktop_ui.test.js` (node): detection matrix, override, geometry
  clamp/cascade, persistence, taskbar rule, WindowManager open/focus/
  minimise/maximise/close/closeAll/next with a fake WinBox.
- `tests/test_desktop_ui.py`: runs the node test; checks vendored WinBox
  hashes against VENDOR.txt, LICENSE present and Apache-2.0, header intact,
  no CDN URLs, THIRD_PARTY_NOTICES lists WinBox, build scripts copy it, the
  hooks exist (lock closes windows), and index.html loads the files.
- Full suite stays green.

## Screens

Headless Chrome at 1920×1080 (launcher open; several windows, one active;
one minimised; one maximised; tray) and 390×844 (mobile unchanged), against a
mock backend on the box and, where possible, the aa-test1 VM with the new UI
files hot-copied.

## Known limits / later

- Add-ons (cross-origin ports), ONLYOFFICE, Node-RED, Agent Zero stay tabs.
- No snapping/tiling, no virtual desktops, no window restore after reload.
- Chat content inside a small window uses viewport media queries, so a narrow
  Chat window keeps the wide layout (container queries later).
