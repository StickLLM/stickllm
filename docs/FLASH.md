# Flashing StickLLM to USB

**Warning:** Flashing a hybrid ISO **erases** the target USB. Confirm the device
node / disk number before writing.

## Get the ISO

| Image | Where | Checksum |
|---|---|---|
| **Current** v0.8.8 | Google Drive `StickLLM-v0.8.8.iso` | [`checksums/v0.8.8.sha256`](../checksums/v0.8.8.sha256) → `c5aa2305…` |
| **N-1** v0.8.7 | Google Drive `StickLLM-v0.8.7.iso` | [`checksums/v0.8.7.sha256`](../checksums/v0.8.7.sha256) → `5e554919…` |

**Hash of record is in this repo** (`checksums/v0.8.8.sha256`). Verify the Drive download against that digest — do not treat a hash only on Drive as authoritative. Previous published ships stay under their own names — never overwrite those files with different contents. Never touch Drive golden **v0.2**.

N-1 restore: `StickLLM-v0.8.7.iso` — see [RESTORE.md](RESTORE.md).

## Verify SHA-256

```powershell
(Get-FileHash .\StickLLM-v0.8.8.iso -Algorithm SHA256).Hash
```

```bash
sha256sum StickLLM-v0.8.8.iso
```

## Windows

1. Download [Rufus](https://rufus.ie/).
2. Select the verified ISO.
3. Choose **DD Image** mode (not ISO mode).
4. Write to the USB stick.
5. **Full readback (required for v0.8.0+):** compare the written ISO byte length back from the USB to the source ISO (byte-for-byte). Fail the flash if they differ. Maintainer lab: elevated `out/safe-flash-lexar-auth.py` (or Samsung script) now does write + readback.

After an isohybrid flash, Windows often shows **no drive letter**. The disk is
still there — confirm with disk number / size / bus (Get-Disk), not Explorer.

Avoid naive PowerShell `FileStream` raw write (Access Denied even when elevated).

## Linux

```bash
lsblk -d -o NAME,SIZE,MODEL,TRAN
# REPLACE sdX with your USB device
sudo wipefs -a /dev/sdX
sudo dd if=StickLLM-v0.8.3.iso \
  of=/dev/sdX bs=4M status=progress oflag=sync
# Full readback (required for v0.8.0+)
sudo cmp -n "$(stat -c%s StickLLM-v0.8.3.iso)" StickLLM-v0.8.3.iso /dev/sdX
sudo eject /dev/sdX
```

Optional helper (same `dd` path):

```bash
ISO=StickLLM-v0.8.3.iso ./scripts/flash-linux.sh /dev/sdX
```

## macOS

```bash
diskutil list
ISO=StickLLM-v0.8.3.iso ./scripts/flash-macos.sh /dev/diskN
```

## After flash

1. Eject the stick.
2. Follow [BOOT.md](BOOT.md).
3. First boot can claim free space as `STICKLLM-DATA` for durable model downloads,
   and reserve about 256 MB beside the live image for the encrypted settings
   partition (same vault passcode; not a file inside the ISO). Until DATA
   exists, models live in RAM and are lost on reboot.
4. Confirm Debian 13: `grep VERSION_ID /etc/os-release` should show `13`.

## Debian 13 line — **v0.8.3**

NInfer-all Linux builds need **Debian 13**. Artifact:
`out/v0.8.3/StickLLM-v0.8.3.iso` (fresh image, not an in-place dist-upgrade),
flashed then verified with a **full readback** of the written ISO bytes. See
[DEBIAN13-EXPERIMENTAL.md](DEBIAN13-EXPERIMENTAL.md). Never overwrite shipping ISO names
(`v0.8.2`, `v0.8.1`, `v0.8.0`, golden `v0.2.0`).
