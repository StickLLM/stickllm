# StickLLM UI mockup — feature inventory & IA

Standalone comprehensive mockup. Does **not** replace `ui/` production.
Source of truth: `ui/index.html`, `ui/app.js`, `FEATURES.md`, `docs/VAULT.md`, `docs/MODELS.md`.

**Inventory count: 76 client-reachable functions** (SSH password excluded — terminal-only).

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
| 1 | Brand “StickLLM” | header `.brand` | Chat chrome + drawer header |
| 2 | Status line (model / uplink / pair) | `#statusLine` | Thin status strip under header (not per-message) |
| 3 | Pair code display | `#connectPair` | Status strip + Pair panel |
| 4 | LAN URL | `#connectUrl` | Status strip + Pair panel |
| 5 | Active model name | `#connectModel` | Status strip + Models panel header |
| 6 | Mode: Ephemeral \| Vault | `#sessionMode` | Header segmented control + drawer footer |
| 7 | Web lookup toggle | `#webToggle` | Composer toolbar (toggle only; never echoed in bubbles) |
| 8 | Lock vault | `#lockVaultBtn` / Ctrl+Shift+L | Header lock + drawer “Lock vault” |
| 9 | Pair (remint / enter code) | `#pairBtn` + `#pairDialog` | Hamburger → Pair sheet |
| 10 | Models open | `#modelsBtn` | Hamburger + desktop chrome “Models” |
| 11 | Settings open | `#settingsBtn` | Hamburger → Settings (Network / System tabs) |
| 12 | Chats open (Vault mode) | `#chatsBtn` | Hamburger + sidebar chat list (gated) |
| 13 | Chat thread | `#log` | Main column |
| 14 | Composer textarea + Send | `#composer` | Bottom chrome |
| 15 | Session footer hint | `#apiHint` | Drawer footer / status |
| 16 | Pair: enter 6-digit code | `#pairCode` | Pair sheet |
| 17 | Pair: submit / cancel | `#pairForm` | Pair sheet |
| 18 | Models: backend / VRAM / loaded status | `renderModelsStatus` | Models panel status block |
| 19 | Models: download progress bar | `#dlProgress` | Models panel |
| 20 | Probe VRAM / recommend | `#actProbe` | Models → actions |
| 21 | Download recommended | `#actDownload` | Models → actions |
| 22 | Refresh catalog | `#actRefresh` | Models → actions |
| 23 | Catalog radio select | `.catalogRadio` | Models → catalog list |
| 24 | Context size slider | `#ctxSlider` | Models → selection panel |
| 25 | Activate / Reload with context | `#actActivate` | Models → selection panel |
| 26 | Download this model | `#actModelDownload` | Models → manage |
| 27 | Delete selected model | `#actModelDelete` | Models → manage |
| 28 | Delete confirm “ARE YOU SURE” | `#deleteConfirmDialog` | Modal |
| 29 | Settings summary (backend / USB / uplink) | `#settingsBody` | Settings → Overview |
| 30 | Network online status | `#netStatus` | Settings → Network |
| 31 | WiFi SSID | `#wifiSsid` | Settings → Network |
| 32 | WiFi password | `#wifiPass` | Settings → Network |
| 33 | Connect WiFi | `#wifiConnect` | Settings → Network |
| 34 | Vault status line | `#vaultStatus` | Vault panel header |
| 35 | Disk / storage list (read-only) | `#diskList` | Vault → Storage list |
| 36 | Claim USB free space | `#actClaim` | Vault → Storage actions |
| 37 | List storage (read-only) | `#actVaultDisks` | Vault → Storage actions |
| 38 | Lock vault (settings/vault) | `#actVaultLock` | Vault + header Lock |
| 39 | Refresh settings / vault | `#actSettingsRefresh` | Vault / Settings refresh |
| 40 | Refresh devices | `#actVaultPickerRefresh` | Vault → Device picker |
| 41 | Device Open (selectable mounts) | vault device “Open” | Vault → Device list |
| 42 | Mount host SSD volume | Mount button | Vault → Device list (unmounted) |
| 43 | Browse folders Up | `#actVaultBrowseUp` | Vault → Folder browser |
| 44 | Use this folder | `#actVaultBrowseUse` | Vault → Folder browser |
| 45 | Open existing vault | `#actVaultUseExisting` | Vault → Folder browser |
| 46 | New folder… | `#actVaultBrowseNew` | Vault → Folder browser |
| 47 | Find existing models | `#actVaultFindModels` | Vault → Folder browser |
| 48 | Find existing vault | `#actVaultFindExisting` | Vault → actions |
| 49 | Model search hits | `#vaultModelHits` | Vault → hits list |
| 50 | Selected vault path | `#vaultSetupPath` | Vault → path field |
| 51 | Create: initial blob size GiB | `#vaultSetupSize` | Vault → Create section |
| 52 | Create: new passcode | `#vaultSetupPass` | Vault → Create section |
| 53 | Create: confirm passcode | `#vaultSetupPass2` | Vault → Create section |
| 54 | Type CREATE-VAULT | `#vaultSetupConfirm` | Vault → Create section |
| 55 | Create vault here | `#actVaultSetup` | Vault → Create section |
| 56 | Recovery phrase (once) | `#vaultRecovery` | Vault → after create |
| 57 | Type SAVED | `#vaultSetupSaved` | Vault → after create |
| 58 | Finish setup (SAVED) | `#actVaultSetupFinish` | Vault → after create |
| 59 | Unlock passcode | `#vaultPass` | Vault → Unlock |
| 60 | Unlock vault | `#actVaultUnlock` | Vault → Unlock |
| 61 | Grow blob by GiB | `#vaultGrowGb` | Vault → Advanced |
| 62 | Grow vault | `#actVaultGrow` | Vault → Advanced |
| 63 | Wipe-after-N tries | `#vaultWipeN` | Vault → Advanced |
| 64 | Apply wipe setting | `#actVaultWipe` | Vault → Advanced |
| 65 | Movable USB models list | `#movableList` | Vault → Move models |
| 66 | Refresh movable | `#actVaultMovable` | Vault → Move models |
| 67 | Move → vault (per model) | Move buttons | Vault → Move models |
| 68 | How to load a model | System copy | Settings → System |
| 69 | How to connect / pair | `#howToConnect` | Settings → System + Pair |
| 70 | Coming later stubs | `.futurePanel` | Settings → System (muted) |
| 71 | Saved chats list | `#chatsList` | Drawer / Chats sheet (Vault) |
| 72 | New chat | `#actChatNew` | Drawer + Chats sheet |
| 73 | Save current chat | `#actChatSave` | Chats sheet |
| 74 | Open saved chat | Open per row | Chats sheet |
| 75 | Delete saved chat | Delete per row | Chats sheet |
| 76 | Attach + Mic reserved | (planned FEATURES) | Composer slots (disabled) |

### Explicitly excluded from client mockup

| Item | Why |
|------|-----|
| SSH password / `#sshCredPanel` | Terminal / loopback Test-Term only; never shown to LAN client |
| Boot-time vault unlock | Product rule: Mode stays Ephemeral; unlock only in UI |
| “Web on” per assistant message | User constraint — web is a composer toggle only |

---

## Information architecture

```
┌─ Chat chrome (always) ─────────────────────────────────────┐
│ ☰  StickLLM   [Ephemeral|Vault]   status · Lock            │
│     (desktop also: Models · Vault · Settings)              │
├────────────────────────────────────────────────────────────┤
│  Status strip: Pair · URL · Model · uplink (glance only)   │
├──────────────┬─────────────────────────────────────────────┤
│ Drawer       │  Chat thread                                │
│ (hamburger)  │                                             │
│ New chat     │                                             │
│ Chats*       │                                             │
│ Models       │                                             │
│ Vault        │                                             │
│ Pair         │                                             │
│ Settings     │                                             │
│ Lock vault   │                                             │
│ Mode + hint  │                                             │
├──────────────┴─────────────────────────────────────────────┤
│ Composer: [Attach] [textarea] [Mic] [Send]  · Web toggle   │
└────────────────────────────────────────────────────────────┘

Sheets / panels (full coverage, fake data, clickable):
  Models | Vault | Pair | Settings(Network·System) | Chats | Delete confirm
```

\* Chats visible when Mode = Vault (and unlocked in mockup state).

### Hamburger vs main chrome

| In hamburger / drawer | In main chat chrome |
|-----------------------|---------------------|
| New chat, chat list | Brand |
| Models, Vault, Pair, Settings | Mode segmented control |
| Lock vault | Compact status + Lock (desktop) |
| Session / pair hint | Models · Vault · Settings (desktop ≥900px) |
| Mode duplicate | Hamburger button (mobile) |

Vault is a **first-class panel** (not only a Settings subsection) so Mount SSD / create / unlock / find are discoverable.

---

## Visual direction

- StickLLM forest / moss DNA (`#0f1410`, accent `#3dcc7a`) — not purple AI slop.
- Fonts: **Syne** (brand), **DM Sans** (UI), **IBM Plex Mono** (codes / paths).
- Motion: drawer slide, sheet rise, bubble enter, mode pulse on Vault.
- Mobile-first drawer; desktop optional persistent rail.

## Serve

```bash
npx --yes serve ui/mockup -p 8765
# → http://127.0.0.1:8765/
```
