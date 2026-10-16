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
| 23 | Catalog radio select | S › Models › Library (radio list with trust level, licence, format, capabilities, abliterated tag and estimated tok/s; filters above) |
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
| 36 | Claim USB free space | S › Storage & Vault › StickLLM stick › "Use free space on the stick" › Set up… (typed CLAIM). It only partitions the StickLLM stick itself, never the user's drives |
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
### Model Browser (S › Models)
- **Tabs:** *Browse Hugging Face* (a mock catalog snapshot; nothing goes over the network) and *On this machine* (installed models + presets/Advanced/Reload). Both tabs share the same filter sidebar.
- **Filter sidebar:**
  - Target hardware dropdown (This machine / Home server / Office PC / Custom VRAM+RAM) with the detected hardware line, e.g. "RTX 3090 24 GB, RAM 192 GB".
  - **Fits this hardware** checkbox, plus "Context for fit check" (8k/32k/128k).
  - Trust (5 levels).
  - Abliterated/uncensored: Include / Only / Exclude.
  - Type (chat/coder/vision/embedding), Architecture (Any/Dense/MoE), Quant, Can do, Licence, Format, and the pickle note.
  - Reset filters.
- **Toolbar:** search box; Sort (Best fit / Downloads / Newest / Size).
- **Cards:**
  - Name, org, licence, format, downloads, date and location.
  - Tags: trust, ⚠ uncensored (amber), gated badges, type, architecture (e.g. "MoE · 235B / 22B active") and capabilities.
  - **Quant-variant dropdown**, where each option shows size and fit.
  - **Fit badge:** Fits on GPU / Fits with CPU offload (MoE) / Won't fit. It's worked out from weights + KV cache at the chosen context and KV type (+1 GB overhead). Only MoE models get the offload option; dense models that are too big show Won't fit.
  - Estimated tok/s on the target.
  - Actions: Download (inline progress bar, hash-verified when done), Load, Set default, or Delete file (blocked models only).
- **Hugging Face token** (Browse tab): masked input with a show toggle and **Test** (mock check). Status reads "Saved to vault" when the vault is unlocked, otherwise "Session only, cleared at shutdown". There's a hint to use a read-only, fine-grained token. Gated models show **🔑 Needs HF token** (no token) or **Gated: accept terms on HF** (token present but terms not accepted), and Download stays disabled until it's resolved.
- **Uncensored warning:** an amber "⚠ uncensored" tag, and a one-time acknowledgement dialog before the first download or load of an abliterated model. The dialog has the required text, an "I understand" checkbox, and Continue (disabled until it's ticked).
- **Per-machine profiles:**
  - The header shows a machine chip (e.g. "Home server" / "Office PC"); clicking it opens S › System › This machine.
  - That section has: machine name, detected hardware, **Only allow Verified models on this machine**, **Hide uncensored models on this machine**, and a **Default model** that's remembered per machine. There's also a mockup-only "Simulate boot on" switch.
  - When policy applies, Models shows a banner, locks the matching filters, prints "N hidden by machine policy", and disables Load for disallowed models.
- **Example data:**
  - Qwen3-235B-A22B abliterated Q4_K_M at 128 GB fits Home server (24 GB VRAM + 192 GB RAM) with offload, and won't fit Office PC (24 + 64 GB).
  - Kimi-K3 (1.4T MoE) won't fit either machine.
  - Verified Qwen3-32B Q4_K_M (19.8 GB) fits on the GPU and is the default/running model.
  - Others: gpt-oss-20b, Mixtral-8x22B (gated), gemma-3-27b (gated, safetensors, non-commercial), Qwen2.5-Coder, Qwen2.5-VL, nomic-embed, Llama-3.1-8B (+ a Verified abliterated build), an untrusted uncensored model, and a blocked hash-mismatch file.
- **Model trust levels (5):** Verified (StickLLM hash + tested), Community verified (official publisher repo, hash matches, not tested by us), Unverified, Untrusted (unknown source; download needs a typed DOWNLOAD confirm), Blocked (hash mismatch: shown greyed, radio disabled, reason in red, can't load; also left out of "Move models into vault"). **Abliterated** is a separate tag, so a Verified model can also be abliterated.
- **Library filters:** Trust (multi-toggle), Licence (Any / Commercial OK / Non-commercial), Can do (Tool calling, Vision, Long context, Reasoning; must have all selected), plus Reset filters and an "N of M" count. **GGUF only** (llama.cpp) — no safetensors format chooser. A note says pickle `.bin`/`.pt` checkpoints are never offered because they can run code on load.
- **Estimated tok/s** on each model row (fake estimate for the target GPU from memory bandwidth ÷ model size).
- Presets Fast / Balanced / Long context; KV cache type f16/q8_0/q4_0; temperature, top-p, top-k, repeat penalty, max tokens; Reset to preset; a "modified" marker on the preset.
- VRAM budget bar that turns red with a warning when the selection won't fit.
- A calm note in Storage & Vault: "StickLLM never partitions or formats your own drives. To prepare one, use your computer's disk tools." The vault is only ever created as a file inside an existing drive, partition or folder.
- Paired-devices list with Revoke / Revoke all; chat export (.json, per chat or all); offline-mode switch; Tor placeholder; backend picker Auto/CUDA/Vulkan/CPU; GPU and RAM info; version and Check for updates; About; light/dark theme; keyboard shortcut list; Esc closes the top layer; arrow keys move through the settings nav.

## Shared picker component (one modal, three modes)
- **folder**: pick a folder (Create vault › Folder, Models › Models folder).
- **vault**: folder mode that can also select a "StickLLM vault" file and switches the button to **Open vault** (Vault location, drive cards).
- **file**: used by the composer **Attach** button. Same sidebar (plus Places: Pictures/Documents/Downloads), breadcrumb and list, with an Images / Documents / All filter, list/grid toggle with image thumbnails, multi-select (click toggles, Shift-click ranges, Space, Ctrl+A, selection kept across folders) and a footer **Attach (N)**. Double-click a file to attach it right away.

Common to all modes: a drive sidebar, Back/Forward/Up, breadcrumb with an editable path, a list (name/modified/size) with single-click select and double-click open, arrow keys/Home/End/Enter/Backspace/Alt+arrows, auto-badges for vault files and models, a new-folder icon, and a footer with the selected path plus Cancel and Select folder / Open vault. It only browses and creates folders, never partitions or formats the user's drives.

## Dropped or merged
- "Find existing vault" / "Find existing models" on Storage: restored in the file picker as **Search for vault** / **Search for models** (toolbar + sidebar), wired to `vault_find` / `vault_find_models`.
- Whole-partition vault creation (an earlier draft of this mockup) and its ERASE-PARTITION confirm: removed for the same reason.
- #37, #39, #40: three refresh/list actions merged into one Drives › Refresh (the list renders automatically).
- #21 "Download recommended": no separate button. The recommended model is tagged in the list and downloaded with the normal Download action.
- #70 "Coming later" panel: replaced by inline placeholders.
- SSH password (`#sshCredPanel`): **excluded on purpose.** System › Help only says "Login details are shown on the stick's console only."
- The pair code was moved out of the always-visible status strip (Cursor's mockup showed it to every LAN browser).
