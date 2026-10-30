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
