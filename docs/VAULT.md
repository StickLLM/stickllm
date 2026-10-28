# Encrypted SSD vault (v0.3.6 / `feature/encrypted-ssd-vault`)

**Creates a file in a folder you choose. Never formats your drive.**

Shipping ISO: **v0.3.6** on Google Drive — see [RESTORE.md](RESTORE.md) / [README.md](../README.md).
**Do not flash v0.3.5** (truncated).

## Session mode (UI header)

| Mode | Behavior |
|---|---|
| **Ephemeral** (default) | No SSD/vault writes. Chats stay RAM-only as today. Downloads use USB DATA or baked RAM paths only. |
| **Vault** | User must switch consciously. Downloads/chats may use the encrypted blob after unlock/setup. |

Switching to Vault opens Settings unlock/setup if the vault is locked or absent. Switching back to Ephemeral stops new vault writes (does not auto-lock; use **Lock** / Ctrl+Shift+L to close LUKS).

**Boot:** no vault password/skip prompt. Session Mode stays **Ephemeral**; the vault stays locked until the user unlocks (or creates/attaches) in the UI. Headless Server/Local must not wait on tty for vault input. Chats APIs refuse to write unless Mode is Vault **and** the vault is mounted.

## Safety (fail-closed)

Encoded from product docs and shipping rules:

| Rule | Source |
|---|---|
| Never auto-touch internal disks; USB claim = boot stick only | [MODELS.md](MODELS.md), [THREAT-MODEL.md](THREAT-MODEL.md) |
| Host internal disks must not be written by default | [THREAT-MODEL.md](THREAT-MODEL.md), [HARDWARE.md](HARDWARE.md) |
| SSD path = user-chosen **file** only; refuse EFI/system/BitLocker | [MODELS.md](MODELS.md) |
| Wipe-after-N **default off**; typed confirm if enabled | [MODELS.md](MODELS.md), `catalog.toml` `[vault]` |
| Never auto-format; never partition for vault | FEATURES + this branch |

**v0.3.6 posture:**

1. **Encrypted host volume** (BitLocker, host LUKS, etc.) → do not unlock, reformat, or re-encrypt. User unlocks/mounts in the **host OS** first.
2. **Unknown / RAID / LVM / exotic / ambiguous** partition layout → refuse; do not offer as a write target.
3. **Only** act on a clearly **mounted, writable, ordinary** filesystem: create a directory (if needed) + a **new sparse LUKS2 file blob** after typed `CREATE-VAULT`.
4. **Never** `cryptsetup luksFormat` / wipefs / partition against a block device (`/dev/sd*`, `nvme*`, …).
5. **Never** rewrite partition tables for any reason in v0.3.6.
6. Disk listing is a **read-only** probe. Raw devices are never vault targets.
7. Existing files in a selected `models/` folder are **kept**; move into vault only via explicit `MOVE-MODEL`.
8. Blob growth checks free space and keeps a reserve; wipe-after-N destroys **only** the blob’s LUKS header when user enabled it (default off).

## Layout

```text
<user-chosen-dir>/
  models/                 # create if missing; existing files untouched
  stickllm-vault.img      # sparse expandable LUKS2 + ext4 (chats/settings/…)
```

When unlocked, blob mounts at `/var/lib/stickllm/vault` (`models/`, `chats/`, `settings/`).

## Opening an existing vault

The vault file (`stickllm-vault.img`) is already on the SSD. These steps opened that file from a new stick. Creating a vault is a different action, below. You can also open the same file from **Open an existing vault** on that screen, or with `stickllm-vault attach`.

1. Select Storage and Vault
2. Mount SSD
3. Search for Vault
4. Attach vault
5. Unlock vault

A new USB boot creates a raw ~256 MB settings partition and does not format it. The stick does not already know the vault passcode. Formatting happens when that existing vault is unlocked with the passcode. After unlock, Storage & Vault shows the vault unlocked and `/mnt/stickllm-settings` mounted (about 252 MB free). That area remembers this computer's SSD vault location. Voice model files stay in `/opt/stickllm/speech`.

## Creating a new vault

**Create a new vault file** on the Storage & Vault screen, or `stickllm-vault setup` under Commands, makes a new `stickllm-vault.img` in a folder you choose. Setup refuses if that file is already there and never overwrites it. The SSD is not formatted.

## Commands (SSH)

```bash
sudo stickllm-vault list-disks          # read-only
sudo stickllm-vault setup /mnt/host/StickLLM 32   # NEW blob only
# After reflash (meta wiped, blob still on SSD) — attach without format:
sudo stickllm-vault attach /mnt/stickllm-host/<ssd-mount>/models
# (aliases: use | setup --existing)
sudo stickllm-vault unlock
sudo stickllm-vault lock
sudo stickllm-vault grow 16
sudo stickllm-vault move-model /path/model.gguf
```

### Reflash / “no vault configured”

USB reflash clears ephemeral `/run` + ISO overlay. The LUKS file
`stickllm-vault.img` on the host SSD is untouched. Do **not** Create vault again
in that folder (setup refuses if the blob exists; never overwrites).

**USB DATA pointer (survives ISO reflash if Claim kept `STICKLLM-DATA`):**
after successful setup/attach, StickLLM writes
`/mnt/stickllm-data/stickllm-vault-location.json` with blob path + disk hints
only — **never** the passcode. **Find existing vault** reads that pointer, else
scans `/mnt/stickllm-host` for `stickllm-vault.img`, then attaches + prompts Unlock.

**Current UI:** [Opening an existing vault](#opening-an-existing-vault).

**UI on shipping v0.3.6:** Find/Open existing vault + attach are included. CREATE-VAULT
does **not** attach an existing blob (refuses if img exists). Paste SSH password
from Settings → System (Test/Term, on-stick) for hot-deploy on older sticks.

## USB settings partition (~256 MB)

This is **not** inside the ISO and **not** the SSD vault file. On a stick with
free space beside the live image, `stickllm-usb-claim` reserves about **256 MB**
as its own partition. `STICKLLM-DATA` (models) stays a separate partition.
Claim does **not** shrink a `STICKLLM-DATA` that already goes to the end of the stick.

The partition stays raw until the SSD vault passcode is accepted. Then
`stickllm-usb-settings` formats it LUKS2 Argon2id with **that same passcode**.
There is no second password. If `vault.key` and `vault-meta/recovery.sha256`
already exist, those same slots are added, matching `stickllm-vault` setup.
Boot does not prompt and does not unlock it (`stickllm-vault-boot` is unchanged).

Mounted at `/mnt/stickllm-settings` while the vault is unlocked:

| Path | Contents |
|---|---|
| `computers/<machine-id>.json` | This computer's SSD vault location. Path hints only |
| `secrets/` | Portable secrets (API keys, passwords). The Hugging Face token is stored here |

Voice weights stay in `/opt/stickllm/speech`. Chats stay in the SSD vault blob.

`stickllm-vault-location.json` on `STICKLLM-DATA` is still written. It has no
passcode. Find existing vault can use it **before** the settings partition is
opened. After unlock, the per-computer file inside settings is preferred.

Host disks are unchanged: `stickllm-vault create-partition` stays disabled, and
the settings script refuses any partition that is not the ~256 MB slot on the
boot USB.

## Workflow

SSH-test on a running stick first when iterating. Do not touch older `out/v0.3.*/`
dirs or rewrite published shipping tags/checksums.

### Hot-deploy (running stick, menu 2/3)

Password is **random per boot** (READY screen) — do not invent it.

```bash
# from feature/encrypted-ssd-vault worktree
scp overlay/usr/local/bin/stickllm-vault \
    overlay/usr/local/bin/stickllm-vault-boot \
    overlay/usr/local/bin/stickllm-kiosk \
    overlay/usr/local/bin/stickllm-control \
    stickllm@<ip>:/tmp/
scp ui/app.js ui/index.html ui/style.css stickllm@<ip>:/tmp/stickllm-ui/
ssh stickllm@<ip> 'sudo install -m 755 /tmp/stickllm-vault /tmp/stickllm-vault-boot /tmp/stickllm-kiosk /usr/local/bin/ && sudo install -m 755 /tmp/stickllm-control /usr/local/bin/ && sudo cp /tmp/stickllm-ui/* /opt/stickllm/ui/ && sudo systemctl restart stickllm-control stickllm-ui stickllm-kiosk'
ssh stickllm@<ip> 'sudo stickllm-vault list-disks | tail -c 2000'
# Only setup inside a throwaway *mounted* folder — never /dev/sdX:
# sudo stickllm-vault setup /mnt/somewhere/StickLLM 4
```

### QEMU second disk (no host partitions)

```powershell
# Creates out/_qemu-vault/vault-testdisk.img (ext4 FILE). Leaves out/v0.3.2 alone.
.\scripts\qemu-vault-disk.ps1 -SizeGb 8
```

Attach that image as a virtio disk (`-cpu host` preferred). In-guest mount the
ext4 volume to e.g. `/mnt/vault-test`, then `stickllm-vault setup …`. Do **not**
use the Windows host’s real disks as QEMU drives for vault experiments.
