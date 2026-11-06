# Phone / narrow desktop UI (future)

**Status:** tracked for after 0.6.7 Settings hamburger work. Do not treat as done.

## Problem

The **desktop layout** (`body.deskMode`, WinBox, taskbar, wall icons, launcher) is built for a keyboard/mouse computer. On phones and other small viewports it does not render or use well (cramped taskbar, tiny windows, wall grid, etc.).

Classic (non-desktop) layout already has a narrow path for chat + Settings. Settings section nav on narrow is a **hamburger drawer** as of 0.6.7; that is only Settings, not the whole desk.

## Later work

Optimize the **entire** desktop UI for phones: taskbar, WinBox chrome, launcher, wall icons, and panel layouts. Prefer a real small-screen desk mode (or a clear auto fallback) over squeezing the current desktop chrome.

See also: TODO in `ui/desktop.css` header; CHANGELOG 0.6.7 **Later**.
