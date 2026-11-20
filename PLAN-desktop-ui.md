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

## 0.5.6: every old window/control mapped to a desktop app

Desktop layout only; Classic (phones, tablets, narrow windows, or the Classic
override) is unchanged and still shows all of these in place. Nodes are moved,
not copied, so every existing handler keeps working; leaving the desktop puts
each one back.

| Old place (0.5.5 desktop = Chat window) | 0.5.6 desktop |
| --- | --- |
| Chat thread, composer, attach, voice, mic, send/stop | **Chat** window (chat only, pinned first on the taskbar) |
| Sidebar *New chat* + chat history list | **Chat** window (its own sidebar, collapsible with Ctrl+B) |
| Sidebar Ephemeral / Vault switch + mode hint | **Taskbar** storage switch (Ephemeral · Vault). Vault while locked opens the vault popover with the unlock form; Lock vault and Storage settings from there |
| Header lock button (`#lockBtn`) | Taskbar vault popover *Lock vault*, Start → Lock vault, Ctrl+Shift+L |
| Header model chip + status popover (`#statusChip`/`#statusPop`) | **Taskbar** model button: model name; *Open Model* when none is loaded; click opens **Models** |
| Sidebar *Models*, popover *Manage models*, Settings → Models / Downloads | **Models** window (Models + Downloads tabs). Hidden from the Settings window's nav |
| Sidebar *Storage & Vault*, *Settings*, header gear, Ctrl+, | **Settings** window (General, Storage & Vault, Network, Devices, Chats, System, About) |
| Header pairing link (`.topPair`) | Settings → Devices (pairing) |
| Header theme button | Tray theme button |
| Uplink row of the status popover | Tray network icon → Settings → Network |
| Sidebar *Apps* / Apps page (`#appsView`), *Install apps* catalog | **App Store** window; Start → Apps & installs |
| Sidebar *Agent* link (Agent Zero tab) | **Agent** desktop app: Agent Zero in a window (pop-out button), or install card when not installed |
| Starter apps (Files, Notepad, …) | Unchanged: windows, desktop icons, Start entries |
| Installed catalog apps (ONLYOFFICE, Node-RED, Trilium, …) — 0.5.5: new tabs | Desktop icon + Start entry; open in a window (iframe through the gateway relay, which rewrites `X-Frame-Options`/`frame-ancestors` to StickLLM's own origins). Apps marked `frame: false`, or that still refuse, open with **Pop out** in a real Chromium window |
| — | **Browser** desktop app: a real Chromium window on the stick's screen (see below) |

### Browser (stickllm-control `browser_open` / `browser_status` / `browser_window` / `browser_close`)

The Browser is an ordinary floating desktop window, the way it is on any
desktop: it moves, resizes, minimises to the taskbar, restores, maximises and
closes. To the user the screen is simply their desktop.

- Compositor: the kiosk starts the stock Debian **sway** 1.7 package (MIT,
  unmodified) with `sway -c /etc/stickllm/sway/config`; the distribution
  config is never read. The StickLLM desktop is a chrome-less Chromium
  `--app` window (no tab strip or address bar). It is the single tiled,
  borderless window under everything else. `stickllm-wm watch` finds it by the
  pid `stickllm-sway-session` launched and marks it `stickllm_desktop`.
  Everything else floats on top with a sway title bar: drag the title bar to
  move, drag an edge to resize, Super+drag also works.
- No escape: no bar, no terminal or launcher, no exit or reload binding, no
  Xwayland, no swaynag. The only key bindings are Super+Down (minimise),
  Super+Up (maximise) and Alt+F4 (close), all through `stickllm-wm`, which
  never acts on the desktop window. sway's recommended packages (the foot
  terminal and others) are not installed.
- Fallback ladder: sway → cage → weston kiosk-shell. If sway cannot start
  (rc 70/71, e.g. the GPU) the log records `STICKLLM_KIOSK_SWAY_FALLBACK` and
  cage runs, with full-screen windows as in 0.5.5. In that case
  `browser_window` answers `wm_unavailable`.
- Window control: `stickllm-control` talks to sway's IPC socket using our own
  Python client (`/usr/local/lib/stickllm_wm.py`). There is no linking and no
  swaymsg. Each window is marked `stickllm_bid_<id>`. Normal windows are found
  by `--class=stickllm-browser-<id>`. `--app` pop-outs, whose app_id comes from
  the URL, are found by process session (`getsid(pid)` == launch pid).
  - Placement uses the desktop's requested rect, in physical pixels converted
    to logical ones.
  - Minimise = scratchpad, which the taskbar shows as minimised.
  - Restore = back to the saved rect (`stickllm_rect_*` mark).
  - Maximise = the work area above the 48 px taskbar.
  - Taskbar: a click toggles minimise/restore/focus; right-click gives
    Minimise / Maximise / Close.
- Fresh profiles get `browser.custom_chrome_frame=false`, so Chromium uses the
  compositor frame and there are no dead caption buttons.
- Unchanged safety rules: only the stick's own UI may call these (gateway 403
  `loopback_only` otherwise; a LAN browser's Browser icon opens a normal tab
  on that PC). Each window is a separate Chromium process with a throw-away
  RAM profile in `/run/stickllm/browser/<id>`. Only http(s), at most 4
  windows. `stickllm-download-policy auto` runs before every launch, so
  downloads go only into the unlocked `vault/Downloads` and are blocked while
  the vault is locked.
- Limits:
  - sway 1.7 title bars have no minimise/maximise/close buttons. Adding them
    would need a change to sway's source, which we don't do, so they are
    flagged instead. Use the taskbar or the shortcuts.
  - WinBox windows inside the desktop are always below floating Chromium
    windows.
  - Windows that the desktop Chromium opens itself (Ctrl+N, `target=_blank`)
    float but have no taskbar button.
- Licences: see `THIRD_PARTY_NOTICES.md`. All compositor packages are
  stock Debian and are configured only. Anything that would need a source
  change is flagged rather than done.

### Later (not in 0.5.6): client / app mode

When StickLLM is used from the user's own desktop, phone or tablet (today it
is a browser tab on their PC), a later version will ship it as a wrapped
browser app on their existing desktop. In that mode the host OS window manager
owns the windows, and the Browser icon keeps opening a normal tab or window
there. Not developed yet.

## Windowing options (paused 2026-10-30)

- **A (chosen, paused):** our own small window manager built on wlroots (MIT). It draws our title bars with min/max/close, the taskbar and stacking, so the whole thing feels like a Chromebook.
- **Option L (added at Nink's request, not decided):** a stock, unmodified Linux desktop (e.g. Xfce) on the stick. StickLLM apps (Chat, Models, Vault, Settings, the bundled apps) stay web pages that open as normal windows. A later client/app mode opens the same pages in the user's own browser or a wrapped app, with no StickLLM desktop. Overhead still to be measured in the VM.

**Update 2026-10-30 9:32 AM ET (Nink):** Xfce is added to option A. A now means: a stock, unmodified Xfce desktop (Debian packages, GPL, used as separate programs and configured only through its settings) gives real windows, buttons, a taskbar and stacking, themed and locked down to look like StickLLM (no terminal or exit menus, our wallpaper, and our vault, network and model status). StickLLM's own apps stay web pages in normal windows, so a later client mode can reuse them. Writing our own wlroots window manager is no longer needed unless Xfce falls short. RAM, ISO size and VRAM overhead get measured in the VM when work resumes. Still paused.

**Note 2026-10-30 9:34 AM ET:** Xfce would also run normal Linux apps (e.g. LibreOffice, GIMP, VLC). Use an approved list (Debian/Flathub, or Flatpak sandboxing) and check each licence for commercial redistribution. Nink finds ONLYOFFICE unfriendly; LibreOffice (MPL-2.0, unmodified, scripting API) is a candidate replacement and app-agent target. Not decided.

**Option (not decided) 2026-10-30 9:49 AM ET, platform layout from Nink:**
- **USB boot:** full Xfce desktop.
- **Remote client that boots from the USB:** the same Xfce desktop, with apps from the host machine.
- **Remote desktop from another computer:** the current browser app (or a VM view). The browser version only shows web apps, so non-web Linux apps would need a streamed desktop or VM view.
- **Phone:** the tabbed browser version for now, with native iOS and Android apps later.
- StickLLM's own apps stay web pages so they work in all four.

## 0.5.6 scope update (Nink, 2026-11-02 ~9:00-9:47 PM ET)

Agreed for 0.5.6:
- AMD/Vulkan support for old cards (branch fix/amd-vulkan-detect: sysfs VRAM detect, PCIe-link-aware GPU pick, runtime PM pinned on chosen card, ctx no longer forced to 32768).
- Desktop: Xfce on USB and USB-boot remote clients; existing browser UI kept for phones and remote desktops. Apps unchanged; ONLYOFFICE stays (LibreOffice maybe later).
- Security changes stay paused.
- One Qwen3.5-4B by default for chat AND app control. No hidden second helper. User loads/unloads the app agent and models themselves; nothing auto-loads. Stickman points its model URL at the shared chat llama-server; load/unload UI lives in StickLLM.
- Stickman integration: freeze the slide retrieval pack (30/30 unseen, 6/6 original on current main), plus the Node-RED http-in -> http-response wiring check in service/checker.py. Docs/spreadsheets/full Universal API not shipping yet. Open: add "new slide"/"next page" sections before freeze?
- New knowledge packs: Notepad and Calculator.
- App list: apps that are not installed do not appear at all.
- App targeting (scales to hundreds of apps): no app picker list. The agent acts on the focused or last-used app window by default; "in <App>, ..." routes by name; ambiguous requests go through a small router (4B or keyword match) over installed apps only, retrieving just that app's manual chunks (RAG-style); optional search box + recent apps row instead of a full list.
- Stickman slide pack 7f3b75e (feature/slide-deck-nav: addslide/nextslide/prevslide sections, Node-RED http-in -> http-response check, retrieval 30/30 unseen + 6/6 original) pulled in for 0.5.6 integration (Nink OK 2026-11-02 10:54 PM ET); box clone at /workspace/stickman. Answers the "new slide"/"next page" question above.
