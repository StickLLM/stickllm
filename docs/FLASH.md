# Flashing StickLLM to USB

**Warning:** Flashing a hybrid ISO **erases** the target USB. Confirm the device
node / disk number before writing.

## Get the ISO

| Image | Where | Checksum |
|---|---|---|
| **Current ship v0.3.8** | [Google Drive](https://drive.google.com/drive/folders/1sTgvoyQi3aU-sauolWd35bKTLGynNEd-?usp=sharing) — `StickLLM-v0.3.8.iso` | [`checksums/v0.3.8.sha256`](../checksums/v0.3.8.sha256) → `88f78154…` |

**Hash of record is on GitHub** (`checksums/v0.3.8.sha256` + [Release notes](https://github.com/StickLLM/stickllm/releases/tag/v0.3.8)). Verify the Drive download against that digest — do not treat a hash only on Drive as authoritative.

N-1 restore: `stickllm-amd-rtx3090-v0.3.6.hybrid.iso` + [`checksums/v0.3.6.sha256`](../checksums/v0.3.6.sha256) — see [RESTORE.md](RESTORE.md).

## Verify SHA-256

```powershell
(Get-FileHash .\StickLLM-v0.3.8.iso -Algorithm SHA256).Hash
# expect 88F781545762A986BB3A1DCE9183601B7BBE173D0D56A20CA03BEF7A533201CB
```

```bash
sha256sum StickLLM-v0.3.8.iso
# expect 88f781545762a986bb3a1dce9183601b7bbe173d0d56a20ca03bef7a533201cb
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
sudo dd if=StickLLM-v0.3.8.iso \
  of=/dev/sdX bs=4M status=progress oflag=sync
sudo eject /dev/sdX
```

Optional helper (same `dd` path):

```bash
ISO=StickLLM-v0.3.8.iso ./scripts/flash-linux.sh /dev/sdX
```

## macOS

```bash
diskutil list
ISO=StickLLM-v0.3.8.iso ./scripts/flash-macos.sh /dev/diskN
```

## After flash

1. Eject the stick.
2. Follow [BOOT.md](BOOT.md).
3. First boot can claim free space as `STICKLLM-DATA` for durable model downloads.
   Until that exists, downloads only live in the RAM overlay.
4. After reflashing over a stick that already used an SSD vault blob, use
   Settings → **Find existing vault** / Open existing (see [VAULT.md](VAULT.md)).

Maintainer-only flash tools and lab gates: [MAINTAINER.md](MAINTAINER.md).
