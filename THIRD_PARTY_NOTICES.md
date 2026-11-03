# Third-party notices

StickLLM's own code is under the PolyForm Noncommercial License 1.0.0 (see
`LICENSE`). The components below are bundled in the web UI and keep their own
licences. Each one ships with its full licence text next to its files; this list
is the index. The build copies this file into the image as
`/opt/stickllm/ui/THIRD_PARTY_NOTICES.md`, and the web UI serves it at
`/THIRD_PARTY_NOTICES.md`.

Debian/Linux packages, llama.cpp, Agent Zero, drivers, model weights and the
optional companion apps installed from the Apps catalog are covered by their own
packages and are not listed here.

## WinBox.js 0.2.82

- Used for: the desktop (windowed) layout, `ui/desktop.js`
- Files: `ui/vendor/winbox-0.2.82/` (served as `/vendor/winbox-0.2.82/`)
- Upstream: https://github.com/nextapps-de/winbox
  (npm `winbox@0.2.82`, https://registry.npmjs.org/winbox/-/winbox-0.2.82.tgz)
- Copyright: Thomas Wilkerling, Nextapps GmbH
- Licence: Apache License 2.0 — full text in `ui/vendor/winbox-0.2.82/LICENSE`
- Modifications: none. Pinned version, hashes and provenance in
  `ui/vendor/winbox-0.2.82/VENDOR.txt`. Upstream ships no NOTICE file.

## Bundled starter apps

| App | Upstream | Licence | Licence file |
|---|---|---|---|
| Notepad (text-editor) | https://github.com/GoogleChromeLabs/text-editor | Apache-2.0 | `ui/apps/notepad/LICENSE` |
| Minesweeper (JSMinesweeper) | https://github.com/DavidNHill/JSMinesweeper | MIT, (c) 2022 David N Hill | `ui/apps/minesweeper/LICENSE` |
| Solitaire (SolitaireLib) | https://github.com/zzymyn/SolitaireLib | MIT, (c) 2020 zzymyn | `ui/apps/solitaire/LICENSE` |
| Tetris (javascript-tetris) | https://github.com/jakesgordon/javascript-tetris | MIT, (c) 2011-2016 Jake Gordon and contributors | `ui/apps/tetris/LICENSE` |

Pinned commits and the edits StickLLM made are in each app's `SOURCES.txt`.
Files, Calculator, Media and System monitor are StickLLM's own code.

## Desktop compositor (Debian packages, unmodified)

The desktop session (0.5.6) runs on the stock Debian bookworm packages below,
installed by live-build from the Debian archive exactly as published. StickLLM
does not modify, patch, fork or rebuild them. It configures sway only through
its own config file (`/etc/stickllm/sway/config`, started with `sway -c`) and
talks to it over sway's documented IPC socket from StickLLM's own Python code
(`/usr/local/lib/stickllm_wm.py`, `stickllm-control`). That code is not linked
against these packages and copies no code from them. Each package's full
copyright and licence text ships in the image as
`/usr/share/doc/<package>/copyright`, as Debian provides.

| Package (Debian bookworm) | Version | Upstream | Licence |
|---|---|---|---|
| sway | 1.7-6 | https://github.com/swaywm/sway | Expat (MIT); some protocol XML files MIT-like; `protocols/idle.xml` LGPL-2.1+ (protocol description, unmodified) |
| swaybg | 1.2.0-1 | https://github.com/swaywm/swaybg | Expat (MIT) / MIT-like |
| libwlroots10 (wlroots) | 0.15.1-6 | https://gitlab.freedesktop.org/wlroots/wlroots | Expat (MIT); `protocol/idle.xml` LGPL-2.1+; Debian packaging files GPL-2+; one CC0-1.0 file |

`libwlroots10` was already in the image for the fallback compositor (cage).
sway's other dependencies (Mesa, libglvnd, polkitd, json-c, pango, ...) are
ordinary Debian packages that were already present or are pulled in unchanged;
their licence texts are likewise in `/usr/share/doc/<package>/copyright`.
sway's *recommended* packages (the foot terminal, suckless-tools,
sway-backgrounds) are **not** installed: the image is built with recommends off.

### Xfce desktop (0.5.6, Debian packages, unmodified)

On the stick's own screen the desktop is stock Xfce 4.18 on Xorg, installed
from the Debian bookworm archive exactly as published (recommends off). StickLLM
does not modify, patch, fork or rebuild Xfce or Xorg. It only writes their
settings: xfconf XML defaults (`/etc/stickllm/xfce/xdg`), panel launchers and
an xfdesktop wallpaper written by `stickllm-xfce-session`, an Xfce
`/etc/xdg/xfce4/kiosk/kioskrc`, and an Xorg config file generated at start by
`stickllm-kiosk`. StickLLM's apps open in Chromium windows; no StickLLM code is
linked against Xfce or Xorg. Licence texts ship as
`/usr/share/doc/<package>/copyright`.

| Package (Debian bookworm) | Upstream | Licence |
|---|---|---|
| xfwm4, xfce4-panel, xfce4-session, xfce4-settings, xfdesktop4, xfconf (and their libxfce4ui/libxfce4util/garcon/exo libraries) | https://xfce.org | GPL-2+ (programs), LGPL-2+ (libraries) |
| xserver-xorg-core, xserver-xorg-input-libinput, x11-xserver-utils | https://x.org | MIT/X11 and similar permissive licences |
| dbus-x11 | https://www.freedesktop.org/wiki/Software/dbus/ | AFL-2.1 or GPL-2+ |
| adwaita-icon-theme | https://gitlab.gnome.org/GNOME/adwaita-icon-theme | LGPL-3 or CC-BY-SA-3.0 |

These are used as unmodified Debian binaries, with their source available from
the Debian archive (`apt-get source <package>`). Xfce's recommended packages
(xfce4-terminal, thunar, xfce4-appfinder, ...) are **not** installed.

`grim` (MIT) was used only to take screenshots in a test VM; it is not in the
image's package list.

