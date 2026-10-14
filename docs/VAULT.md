# Encrypted SSD vault (feature branch)

**Branch:** `feature/encrypted-ssd-vault`  
**Workflow:** SSH-test on a running stick first → one clean ISO + QEMU `-cpu host`
with a second virt disk → **do not tag/push/ask to flash** until v0.3.1 HW confirm.

## Behavior

- Settings → Storage lists disks / free space (`stickllm-vault list-disks`).
- Create vault:
  - **File container** (non-destructive): `sudo stickllm-vault create-file /path/vault.img 64`
    — typed `CREATE-FILE`.
  - **Whole partition** (destructive): `sudo stickllm-vault create-partition /dev/sdXN`
    — typed `ERASE-PARTITION` + device path again.
- LUKS2 + Argon2id + ext4. Unlock = passcode (+ optional stick keyfile at
  `/etc/stickllm/vault.key`). Recovery phrase shown **once** at creation.
- Mount: `/var/lib/stickllm/vault` with `models/`, `chats/`, `settings/`.
- Boot helper `stickllm-vault-boot`: unlock or **skip** (locked / no vault models).
- Downloads prefer vault when unlocked; `move-model` copies stick→vault with SHA-256
  verify. Verify again at load via `*.sha256`.
- Multi-chat JSON only under vault `chats/` (no plaintext elsewhere).
- UI **Lock** + **Ctrl+Shift+L**: unload model, umount, `cryptsetup close`.
- Wrong-PIN wipe after N: default **off**; when on, destroys LUKS header.
- Never touches a disk without typed confirm; never auto-formats.

## SSH test sketch

```bash
scp overlay/usr/local/bin/stickllm-vault* stickllm@<ip>:/tmp/
ssh stickllm@<ip> 'sudo install -m 755 /tmp/stickllm-vault /usr/local/bin/ && sudo stickllm-vault list-disks'
# QEMU: second virt disk, then create-file on that disk's filesystem or partition.
```

## QEMU proof (after clean bake)

Use `-cpu host` and a second disk image. Do not request HW flash for this branch
until the user confirms v0.3.1 on 3090 + ASUS.
