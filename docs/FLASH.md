# Flashing StickLLM to USB

**Warning:** Flashing a hybrid ISO **erases** the target USB. Confirm the device
node / disk number before writing.

## Get the ISO

| Image | Where | Checksum |
|---|---|---|
| **Current image v0.4.2** | [Google Drive folder](https://drive.google.com/drive/folders/1sTgvoyQi3aU-sauolWd35bKTLGynNEd-?usp=sharing) — file `StickLLM-v0.4.2.iso` | [`checksums/v0.4.2.sha256`](../checksums/v0.4.2.sha256) → `3a50eb56…` |

**Hash of record is in this repo** (`checksums/v0.4.2.sha256`). Verify the Drive download against that digest — do not treat a hash only on Drive as authoritative. Do not publish the older file of the same name (`f31b5353…`). Previous published ship: `StickLLM-v0.3.9.iso` (`32a37a66…`). `StickLLM-v0.3.8.iso` (`88f78154…`) stays available.

N-1 restore: `stickllm-amd-rtx3090-v0.3.6.hybrid.iso` + [`checksums/v0.3.6.sha256`](../checksums/v0.3.6.sha256) — see [RESTORE.md](RESTORE.md).

## Verify SHA-256

```powershell
(Get-FileHash .\StickLLM-v0.4.2.iso -Algorithm SHA256).Hash
# expect 3A50EB56A7D2FC4E6A55AABFCCC0971E38DDE2B5560BE3B6892FA6AA38572EF7
```

```bash
sha256sum StickLLM-v0.4.2.iso
# expect 3a50eb56a7d2fc4e6a55aabfccc0971e38dde2b5560be3b6892fa6aa38572ef7
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
sudo dd if=StickLLM-v0.4.2.iso \
  of=/dev/sdX bs=4M status=progress oflag=sync
sudo eject /dev/sdX
```

Optional helper (same `dd` path):

```bash
ISO=StickLLM-v0.4.2.iso ./scripts/flash-linux.sh /dev/sdX
```

## macOS

```bash
diskutil list
ISO=StickLLM-v0.4.2.iso ./scripts/flash-macos.sh /dev/diskN
```

## After flash

1. Eject the stick.
2. Follow [BOOT.md](BOOT.md).
3. First boot can claim free space as `STICKLLM-DATA` for durable model downloads,
   and reserve about 256 MB beside the live image for the encrypted settings
   partition (same vault passcode; not a file inside the ISO). Until DATA
   exists, downloads only live in the RAM overlay. A stick whose DATA partition
   already fills the disk is not shrunk.
4. When the vault file is already on the SSD, open it with
   [Opening an existing vault](VAULT.md#opening-an-existing-vault).

Maintainer-only flash tools and lab gates: [MAINTAINER.md](MAINTAINER.md).
