# StickLLM UI mockup — feature inventory & IA

Standalone comprehensive mockup. Does **not** replace `ui/` production.
Source of truth: `ui/index.html`, `ui/app.js`, `FEATURES.md`, `docs/VAULT.md`, `docs/MODELS.md`.

**Inventory count: 76 client-reachable functions** (SSH password excluded — terminal-only).

Visual/IA base: Grok “clean UI” (sidebar + settings modal) restyled with StickLLM forest DNA.
Reference copy of the zip: `ui/mockup-grok-ref/` (do not serve as product mockup).

---

## Hard constraints (user)

1. Never stamp “web on” (or similar status spam) onto every reply bubble.
2. SSH password / system SSH credentials: **terminal-only** — not on this client/web mockup.
3. Every production client function must be reachable and labeled (static/fake data OK).
4. Mobile-aware hamburger; composer reserves **Attach** + **Mic** (disabled, future).
5. No boot-time vault prompt; Mode defaults Ephemeral.

---

## Inventory → UI location

| # | Function | Production source | Mockup location |
|---|----------|-------------------|-----------------|
| 1 | Brand “StickLLM” | header `.brand` | Sidebar header + Settings › About |
| 2 | Status line (model / uplink / pair) | `#statusLine` | Header status chip + popover (model · backend · uplink · vault) |
| 3 | Pair code display | `#connectPair` | Settings › Devices & Pairing (kiosk-only note; not always-visible strip) |
| 4 | LAN URL | `#connectUrl` | Settings › Network + Devices & Pairing |
| 5 | Active model name | `#connectModel` | Header chip + Settings › Models |
| 6 | Mode: Ephemeral \| Vault | `#sessionMode` | Sidebar segmented control (+ Settings › General / Chats) |
| 7 | Web lookup toggle | `#webToggle` | Composer “Web” pill (+ Settings › General default) |
| 8 | Lock vault | `#lockVaultBtn` / Ctrl+Shift+L | Header lock (when unlocked) + Storage & Vault |
| 9 | Pair (remint / enter code) | `#pairBtn` + `#pairDialog` | Settings › Devices & Pairing |
| 10 | Models open | `#modelsBtn` | Sidebar footer + chip › Manage models |
| 11 | Settings open | `#settingsBtn` | Header gear + sidebar footer (Ctrl+,) |
| 12 | Chats open (Vault mode) | `#chatsBtn` | Sidebar conversation list + Settings › Chats |
| 13 | Chat thread | `#log` | Main column |
| 14 | Composer textarea + Send | `#composer` | Bottom composer box |
| 15 | Session footer hint | `#apiHint` | Note under composer + sidebar mode hint |
| 16 | Pair: enter 6-digit code | `#pairCode` | Devices & Pairing |
| 17 | Pair: submit / cancel | `#pairForm` | Devices & Pairing (Esc closes) |
| 18 | Models: backend / VRAM / loaded status | `renderModelsStatus` | Models summary + System |
| 19 | Models: download progress bar | `#dlProgress` | Models (inline while downloading) |
| 20 | Probe VRAM / recommend | `#actProbe` | Models › Re-check GPU |
| 21 | Download recommended | `#actDownload` | Select recommended in library › Download |
| 22 | Refresh catalog | `#actRefresh` | Models › Library › Refresh |
| 23 | Catalog radio select | `.catalogRadio` | Models › Library |
| 24 | Context size slider | `#ctxSlider` | Models › Advanced (+ presets / VRAM bar) |
| 25 | Activate / Reload with context | `#actActivate` | Models sticky footer |
| 26 | Download this model | `#actModelDownload` | Models footer Download |
| 27 | Delete selected model | `#actModelDelete` | Models footer Delete… |
| 28 | Delete confirm “ARE YOU SURE” | `#deleteConfirmDialog` | Shared typed-confirm dialog |
| 29 | Settings summary (backend / USB / uplink) | `#settingsBody` | System + Network sections |
| 30 | Network online status | `#netStatus` | Settings › Network |
| 31 | WiFi SSID | `#wifiSsid` | Settings › Network |
| 32 | WiFi password | `#wifiPass` | Settings › Network |
| 33 | Connect WiFi | `#wifiConnect` | Settings › Network |
| 34 | Vault status line | `#vaultStatus` | Storage & Vault status card |
| 35 | Disk / storage list (read-only) | `#diskList` | Drives cards + folder picker sidebar |
| 36 | Use free space on the stick (Claim USB) | `#actClaim` | Storage & Vault › Drives › **Use free space on the stick** (typed `USE-STICK-SPACE`; partitions **only** the StickLLM USB stick — never user disks) |
| 37 | List storage (read-only) | `#actVaultDisks` | Merged into Drives + Refresh |
| 38 | Lock vault (settings/vault) | `#actVaultLock` | Storage card + header Lock |
| 39 | Refresh settings / vault | `#actSettingsRefresh` | Drives › Refresh |
| 40 | Refresh devices | `#actVaultPickerRefresh` | Drives › Refresh |
| 41 | Device Open (selectable mounts) | vault device “Open” | Drive card / picker sidebar |
| 42 | Mount host SSD volume | Mount button | Drive card Mount |
| 43 | Browse folders Up | `#actVaultBrowseUp` | Picker ↑ / Backspace (+ Back/Forward / crumbs) |
| 44 | Use this folder | `#actVaultBrowseUse` | Picker › Select folder |
| 45 | Open existing vault | `#actVaultUseExisting` | Choose vault file › Open vault |
| 46 | New folder… | `#actVaultBrowseNew` | Picker new-folder |
| 47 | Find existing models | `#actVaultFindModels` | Storage › Find existing models (+ picker badges) |
| 48 | Find existing vault | `#actVaultFindExisting` | Storage › Find existing vault (+ picker badges) |
| 49 | Model search hits | `#vaultModelHits` | `#findHits` list under Drives |
| 50 | Selected vault path | `#vaultSetupPath` | Create vault › Folder |
| 51 | Create: initial blob size GiB | `#vaultSetupSize` | Create vault › Size |
| 52 | Create: new passcode | `#vaultSetupPass` | Create vault › Passcode |
| 53 | Create: confirm passcode | `#vaultSetupPass2` | Create vault › Confirm |
| 54 | Type CREATE-VAULT | `#vaultSetupConfirm` | Typed-confirm dialog |
| 55 | Create vault here | `#actVaultSetup` | Create vault… |
| 56 | Recovery phrase (once) | `#vaultRecovery` | Follow-up dialog |
| 57 | Type SAVED | `#vaultSetupSaved` | Same dialog |
| 58 | Finish setup (SAVED) | `#actVaultSetupFinish` | Finish setup |
| 59 | Unlock passcode | `#vaultPass` | Vault status card |
| 60 | Unlock vault | `#actVaultUnlock` | Vault card Unlock |
| 61 | Grow blob by GiB | `#vaultGrowGb` | Vault options |
| 62 | Grow vault | `#actVaultGrow` | Vault options |
| 63 | Wipe-after-N tries | `#vaultWipeN` | Vault options |
| 64 | Apply wipe setting | `#actVaultWipe` | Vault options (typed WIPE-OK) |
| 65 | Movable USB models list | `#movableList` | Move models into vault |
| 66 | Refresh movable | `#actVaultMovable` | Same › Refresh |
| 67 | Move → vault (per model) | Move buttons | Per-row Move to vault |
| 68 | How to load a model | System copy | System › Help |
| 69 | How to connect / pair | `#howToConnect` | System › Help + Devices intro |
| 70 | Coming later stubs | `.futurePanel` | Inline disabled placeholders (Tor, AP, Attach/Mic) |
| 71 | Saved chats list | `#chatsList` | Sidebar (day groups) + Settings › Chats |
| 72 | New chat | `#actChatNew` | Sidebar New chat (Ctrl+Shift+O) |
| 73 | Save current chat | `#actChatSave` | Settings › Chats › Save now |
| 74 | Open saved chat | Open per row | Sidebar click / Chats › Open |
| 75 | Delete saved chat | Delete per row | Chats › Delete |
| 76 | Attach + Mic reserved | (planned FEATURES) | Composer slots (**disabled**) |

### Explicitly excluded from client mockup

| Item | Why |
|------|-----|
| SSH password / `#sshCredPanel` | Terminal / loopback Test-Term only; never shown to LAN client |
| Boot-time vault unlock | Product rule: Mode stays Ephemeral; unlock only in UI |
| “Web on” per assistant message | User constraint — web is a composer toggle only; sources use collapsed disclosure when used |

---

## Information architecture

```
┌─ Sidebar (hamburger on mobile / Ctrl+B) ───────────────────┐
│ StickLLM · New chat · Ephemeral|Vault · chat list          │
│ Models · Storage & Vault · Settings                        │
├────────────────────────────────────────────────────────────┤
│ Header: chat title · status chip · Lock · theme · Settings │
│ Thread                                                     │
│ Composer box: [Attach*] [Web] … [Mic*] [Send]              │
└────────────────────────────────────────────────────────────┘

Settings modal (left nav):
  General | Models | Storage & Vault | Chats |
  Devices & Pairing | Network | System | About

Shared folder/vault picker + typed-confirm dialogs.
* Attach & Mic reserved (disabled).
```

---

## Visual direction

- StickLLM forest / moss DNA (`#0c110e`, accent `#3dcc7a`) — not purple AI slop; teal from Grok zip retuned to moss green.
- Fonts: **Syne** (brand), **DM Sans** (UI), **IBM Plex Mono** (codes / paths).
- Motion: sidebar slide, modal open, bubble enter, typing dots, toast.
- Borrowed from Grok: status chip + popover, settings left-nav modal, composer box, drive cards, VRAM/presets, shared picker, pair code off the always-visible strip.

## Serve

```bash
npx --yes serve ui/mockup -p 8765
# → http://127.0.0.1:8765/
```
