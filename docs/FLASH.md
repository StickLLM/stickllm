# Flashing StickLLM to USB

**Warning:** Flashing a hybrid ISO **erases** the target USB. Confirm the device
node / disk number before writing.

## Get the ISO

| Image | Where | Checksum |
|---|---|---|
| **Current** v0.7.8 | Google Drive `StickLLM-v0.7.8.iso` | [`checksums/v0.7.8.sha256`](../checksums/v0.7.8.sha256) |
| **N-1** v0.7.7 | Google Drive `StickLLM-v0.7.7.iso` | [`checksums/v0.7.7.sha256`](../checksums/v0.7.7.sha256) → `b0071a7b…` |

**Hash of record is in this repo** (`checksums/v0.7.8.sha256`). Verify the Drive download against that digest — do not treat a hash only on Drive as authoritative. Previous published ships stay under their own names — never overwrite those files with different contents. `v0.3.9` is outside the rolling window (removable). Never touch Drive golden **v0.2**.

N-1 restore: `StickLLM-v0.7.7.iso` — see [RESTORE.md](RESTORE.md).

## Verify SHA-256

```powershell
(Get-FileHash .\StickLLM-v0.7.8.iso -Algorithm SHA256).Hash
```

```bash
sha256sum StickLLM-v0.7.8.iso
# expect 10ddd00f44867220e10ee706ea1e3b2eb18c6702db371a2bcccd53572179f840
```

## Windows

1. Download [Rufus](https://rufus.ie/).
2. Select the verified ISO.
3. Choose **DD Image** mode (not ISO mode).
4. Write to the USB stick.

After an isohybrid flash, Windows often shows **no drive letter**. The disk is
still there — confirm with disk number / size / bus (Get-Disk), not Explorer.

Avoid naive PowerShell `FileStream` raw write (Access Denied even when elevated).

## Linux

```bash
lsblk -d -o NAME,SIZE,MODEL,TRAN
# REPLACE sdX with your USB device
sudo wipefs -a /dev/sdX
sudo dd if=StickLLM-v0.7.8.iso \
  of=/dev/sdX bs=4M status=progress oflag=sync
sudo eject /dev/sdX
```

Optional helper (same `dd` path):

```bash
ISO=StickLLM-v0.7.8.iso ./scripts/flash-linux.sh /dev/sdX
```

## macOS

```bash
diskutil list
ISO=StickLLM-v0.7.8.iso ./scripts/flash-macos.sh /dev/diskN
```

## After flash

1. Eject the stick.
2. Follow [BOOT.md](BOOT.md).
3. First boot can claim free space as `STICKLLM-DATA` for durable model downloads,
   and reserve about 256 MB beside the live image for the encrypted settings
   partition (same vault passcode; not a file inside the ISO). Until DATA
   exists, models live in RAM and are lost on reboot.
