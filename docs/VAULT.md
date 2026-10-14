# Encrypted SSD vault (v0.3.3 / `feature/encrypted-ssd-vault`)

**Creates a file in a folder you choose. Never formats your drive.**

## Session mode (UI header)

| Mode | Behavior |
|---|---|
| **Ephemeral** (default) | No SSD/vault writes. Chats stay RAM-only as today. Downloads use USB DATA or baked RAM paths only. |
| **Vault** | User must switch consciously. Downloads/chats may use the encrypted blob after unlock/setup. |

Switching to Vault opens Settings unlock/setup if the vault is locked or absent. Switching back to Ephemeral stops new vault writes (does not auto-lock; use **Lock** / Ctrl+Shift+L to close LUKS).

## Safety (fail-closed)

Encoded from product docs and shipping rules:

| Rule | Source |
|---|---|
| Never auto-touch internal disks; USB claim = boot stick only | [MODELS.md](MODELS.md), [THREAT-MODEL.md](THREAT-MODEL.md) |
| Host internal disks must not be written by default | [THREAT-MODEL.md](THREAT-MODEL.md), [HARDWARE.md](HARDWARE.md) |
| SSD path = user-chosen **file** only; refuse EFI/system/BitLocker | [MODELS.md](MODELS.md) |
| Wipe-after-N **default off**; typed confirm if enabled | [MODELS.md](MODELS.md), `catalog.toml` `[vault]` |
| Never auto-format; never partition for vault | FEATURES + this branch |

**v0.3.3 posture:**

1. **Encrypted host volume** (BitLocker, host LUKS, etc.) → do not unlock, reformat, or re-encrypt. User unlocks/mounts in the **host OS** first.
2. **Unknown / RAID / LVM / exotic / ambiguous** partition layout → refuse; do not offer as a write target.
3. **Only** act on a clearly **mounted, writable, ordinary** filesystem: create a directory (if needed) + a **new sparse LUKS2 file blob** after typed `CREATE-VAULT`.
4. **Never** `cryptsetup luksFormat` / wipefs / partition against a block device (`/dev/sd*`, `nvme*`, …).
5. **Never** rewrite partition tables for any reason in v0.3.3.
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

## Commands (SSH)

```bash
sudo stickllm-vault list-disks          # read-only
sudo stickllm-vault setup /mnt/host/StickLLM 32
sudo stickllm-vault unlock
sudo stickllm-vault lock
sudo stickllm-vault grow 16
sudo stickllm-vault move-model /path/model.gguf
```

## Workflow

SSH-test on a running stick first. **Do not build ISO / tag / push** until the user confirms. Do not touch `out/v0.3.2/` or shipping tags.

### Hot-deploy (running stick, menu 3/4)

Password is **random per boot** (READY screen) — do not invent it.

```bash
# from feature/encrypted-ssd-vault worktree
scp overlay/usr/local/bin/stickllm-vault \
    overlay/usr/local/bin/stickllm-vault-boot \
    overlay/usr/local/bin/stickllm-control \
    stickllm@<ip>:/tmp/
scp ui/app.js ui/index.html stickllm@<ip>:/tmp/stickllm-ui/
ssh stickllm@<ip> 'sudo install -m 755 /tmp/stickllm-vault /tmp/stickllm-vault-boot /usr/local/bin/ && sudo install -m 755 /tmp/stickllm-control /usr/local/bin/ && sudo cp /tmp/stickllm-ui/* /opt/stickllm/ui/ && sudo systemctl restart stickllm-control stickllm-ui'
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
