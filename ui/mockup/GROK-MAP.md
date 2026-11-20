# DESIGN.md inventory (76 items) mapped to the clean UI

Abbreviations: **S** = Settings modal (left nav). **SB** = conversation sidebar. **Hdr** = header. **Cmp** = composer.

| # | Function | Where it lives now |
|---|---|---|
| 1 | Brand | SB header (logo + "StickLLM"); S › About |
| 2 | Status line (model/uplink/pair) | Hdr status chip (model · backend), which opens a popover with model, context, backend, uplink and vault state |
| 3 | Pair code display | S › Devices & Pairing › pair card (labelled "shown on the kiosk only"; it is *not* in the header or any strip) |
| 4 | LAN URL | S › Network › LAN address (Copy); also S › Devices & Pairing pair card |
| 5 | Active model name | Hdr chip; S › Models › "Running" summary |
| 6 | Mode Ephemeral/Vault | SB segmented control (primary); S › General; S › Chats (all three stay in sync) |
| 7 | Web lookup toggle | Cmp "Web" pill; default in S › General. Never stamped on replies; sources go in a collapsed "N web sources" disclosure only when actually used |
| 8 | Lock vault + Ctrl+Shift+L | Hdr lock icon (only shown while unlocked); S › Storage & Vault card; shortcut |
| 9 | Pair (remint) | S › Devices & Pairing › "New code" |
| 10 | Models open | SB footer "Models"; Hdr chip popover › "Manage models" |
| 11 | Settings open | Hdr gear; SB footer "Settings"; Ctrl+, |
| 12 | Chats open (Vault) | SB conversation list (main home); S › Chats for management |
| 13 | Chat thread | Main pane |
| 14 | Composer + Send | Main pane bottom (Enter sends, Shift+Enter adds a new line) |
| 15 | Session footer hint | Note under the composer ("Ephemeral session · runs locally") + mode hint in SB |
| 16 | Pair: enter code | S › Devices & Pairing › "Enter a code" |
| 17 | Pair submit/cancel | Same form ("Pair this browser"); cancel = close/Esc |
| 18 | Backend/VRAM/loaded status | S › Models summary cards; S › System |
| 19 | Download progress bar | S › Models (appears inline while downloading) |
| 20 | Probe VRAM / recommend | S › Models › "Recommended for this GPU" › Re-check GPU |
| 21 | Download recommended | Select the model tagged "recommended" › Download (the generic Download action; see notes) |
| 22 | Refresh catalog | S › Models › Library › Refresh |
| 23 | Catalog radio select | S › Models › Library (radio list) |
| 24 | Context slider | S › Models › Advanced › Context size + VRAM bar (weights / KV cache / free) |
| 25 | Activate / Reload | S › Models sticky footer: "Load model" / "Reload with these settings" |
| 26 | Download this model | S › Models footer "Download" (only shown for models not on disk) |
| 27 | Delete selected model | S › Models footer "Delete…" |
| 28 | Delete confirm ARE YOU SURE | Shared typed-confirm dialog |
| 29 | Settings summary | Split by topic: S › System (backend, stick storage), S › Network (uplink) |
| 30 | Network online status | S › Network › Status |
| 31 | WiFi SSID | S › Network › WiFi |
| 32 | WiFi password | S › Network › WiFi |
| 33 | Connect WiFi | S › Network › Connect |
| 34 | Vault status line | S › Storage & Vault › status card at the top |
| 35 | Disk list | S › Storage & Vault › Drives cards (overview + Mount) and the **Choose folder** dialog sidebar (icon, name, free space; encrypted drives greyed with an "unlock in your OS" tooltip) |
| 36 | Claim USB free space | **Dropped.** It creates a partition, and StickLLM never partitions or formats drives (product decision, 2026-10-15) |
| 37 | List storage (read-only) | Merged into Drives (the list shows automatically) + Refresh |
| 38 | Lock vault (settings) | S › Storage & Vault card › Lock |
| 39 | Refresh settings/vault | Merged: Drives › Refresh |
| 40 | Refresh devices | Merged: Drives › Refresh |
| 41 | Device Open | Click a drive in the picker sidebar, or a drive card (opens the picker on that drive) |
| 42 | Mount host SSD | "Mount" on a drive card, or click an unmounted drive in the picker sidebar (mount only, never formatted) |
| 43 | Browse Up | Picker toolbar ↑ (or Backspace); plus Back/Forward, clickable breadcrumb, and an editable path when you click the crumb bar |
| 44 | Use this folder | Picker footer › **Select folder** (selected path shown in the footer) |
| 45 | Open existing vault | Storage & Vault › Vault location › Choose… › select a file badged "StickLLM vault" › **Open vault** (or double-click it) |
| 46 | New folder | Picker toolbar, new-folder icon |
| 47 | Find existing models | **Automatic:** `.gguf` files get a "model" badge and folders show "N models". Models folder chosen with S › Models › Models folder › Change… |
| 48 | Find existing vault | **Automatic:** vault `.img` files get a "StickLLM vault" badge in the picker |
| 49 | Model search hits | Badges in the picker list (no separate results dump) |
| 50 | Selected vault path | Create a new vault file › Folder (read-only) + Choose… (same picker) |
| 51 | Initial size GiB | Create a new vault › Size |
| 52 | New passcode | Create a new vault › Passcode |
| 53 | Confirm passcode | Create a new vault › Confirm |
| 54 | Type CREATE-VAULT | Typed-confirm dialog |
| 55 | Create vault here | Create a new vault › Create vault… |
| 56 | Recovery phrase | Shown once in a follow-up dialog |
| 57 | Type SAVED | Same dialog |
| 58 | Finish setup | Same dialog › Finish setup |
| 59 | Unlock passcode | Vault status card (inline field) |
| 60 | Unlock vault | Vault status card › Unlock (Enter works). Also reachable from SB "Unlock" link and from picking Vault mode while locked |
| 61 | Grow GiB | Vault options › Grow vault |
| 62 | Grow vault | Same |
| 63 | Wipe-after-N | Vault options › Wipe after wrong passcodes |
| 64 | Apply wipe | Same (typed WIPE-OK when N > 0) |
| 65 | Movable models list | Storage & Vault › Move models into vault |
| 66 | Refresh movable | Same › Refresh |
| 67 | Move → vault | Per-row "Move to vault" |
| 68 | How to load a model | S › System › Help (with an "Open Models" jump) |
| 69 | How to connect/pair | S › System › Help (jump) + Devices & Pairing intro text |
| 70 | "Coming later" stubs | **Dropped as a panel.** Replaced by inline, disabled placeholders where the feature will live (Tor toggle, WiFi AP note, Attach/Mic). Inference defaults now exist (presets + Advanced) |
| 71 | Saved chats list | SB (grouped by day) + S › Chats |
| 72 | New chat | SB "New chat" button; Ctrl+Shift+O |
| 73 | Save current chat | S › Chats › Save now (moves an ephemeral chat into the vault) |
| 74 | Open saved chat | Click in SB; S › Chats › Open |
| 75 | Delete saved chat | S › Chats › Delete (per row) + Delete all… |
| 76 | Attach + Mic | **Attach** opens the shared picker in File mode (see below); selected files show as removable chips/thumbnails above the composer and are sent with the message (mock). **Mic** stays a disabled placeholder |

## Added (not in the inventory)
- Presets Fast / Balanced / Long context; KV cache type f16/q8_0/q4_0; temperature, top-p, top-k, repeat penalty, max tokens; Reset to preset; a "modified" marker on the preset.
- VRAM budget bar that turns red with a warning when the selection won't fit.
- A calm note in Storage & Vault: "StickLLM never partitions or formats drives. To prepare a drive, use your computer's own disk tools." The vault is only ever created as a file inside an existing drive, partition or folder.
- Paired-devices list with Revoke / Revoke all; chat export (.json, per chat or all); offline-mode switch; Tor placeholder; backend picker Auto/CUDA/Vulkan/CPU; GPU and RAM info; version and Check for updates; About; light/dark theme; keyboard shortcut list; Esc closes the top layer; arrow keys move through the settings nav.

## Shared picker component (one modal, three modes)
- **folder**: pick a folder (Create vault › Folder, Models › Models folder).
- **vault**: folder mode that can also select a "StickLLM vault" file and switches the button to **Open vault** (Vault location, drive cards).
- **file**: used by the composer **Attach** button. Same sidebar (plus Places: Pictures/Documents/Downloads), breadcrumb and list, with an Images / Documents / All filter, list/grid toggle with image thumbnails, multi-select (click toggles, Shift-click ranges, Space, Ctrl+A, selection kept across folders) and a footer **Attach (N)**. Double-click a file to attach it right away.

Common to all modes: a drive sidebar, Back/Forward/Up, breadcrumb with an editable path, a list (name/modified/size) with single-click select and double-click open, arrow keys/Home/End/Enter/Backspace/Alt+arrows, auto-badges for vault files and models, a new-folder icon, and a footer with the selected path plus Cancel and Select folder / Open vault. It only browses and creates folders, never partitions or formats.

## Dropped or merged
- "Find existing vault" / "Find existing models" buttons: replaced by automatic detection in the picker.
- #36 "Claim USB free space": removed. It partitions the stick, which the never-partition/format rule forbids.
- Whole-partition vault creation (an earlier draft of this mockup) and its ERASE-PARTITION confirm: removed for the same reason.
- #37, #39, #40: three refresh/list actions merged into one Drives › Refresh (the list renders automatically).
- #21 "Download recommended": no separate button. The recommended model is tagged in the list and downloaded with the normal Download action.
- #70 "Coming later" panel: replaced by inline placeholders.
- SSH password (`#sshCredPanel`): **excluded on purpose.** System › Help only says "Login details are shown on the stick's console only."
- The pair code was moved out of the always-visible status strip (Cursor's mockup showed it to every LAN browser).
