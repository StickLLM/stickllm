# Flashing StickLLM to USB

**Warning:** Flashing a hybrid ISO **erases** the target USB. Confirm the device
node / disk number before writing.

## Get the ISO

| Image | Where | Checksum |
|---|---|---|
| **Current ship v0.3.9** | [Google Drive](https://drive.google.com/drive/folders/1sTgvoyQi3aU-sauolWd35bKTLGynNEd-?usp=sharing) — `StickLLM-v0.3.9.iso` | [`checksums/v0.3.9.sha256`](../checksums/v0.3.9.sha256) → `32a37a66…` |

**Hash of record is on GitHub** (`checksums/v0.3.9.sha256` + [Release notes](https://github.com/StickLLM/stickllm/releases/tag/v0.3.9)). Verify the Drive download against that digest — do not treat a hash only on Drive as authoritative. Previous ship: `StickLLM-v0.3.8.iso` (`88f78154…`).

N-1 restore: `stickllm-amd-rtx3090-v0.3.6.hybrid.iso` + [`checksums/v0.3.6.sha256`](../checksums/v0.3.6.sha256) — see [RESTORE.md](RESTORE.md).

## Verify SHA-256

```powershell
(Get-FileHash .\StickLLM-v0.3.9.iso -Algorithm SHA256).Hash
# expect 32A37A66110EA2D2BC113D7C3B940647597252986799B007FA1FC217399A9585
```

```bash
sha256sum StickLLM-v0.3.9.iso
# expect 32a37a66110ea2d2bc113d7c3b940647597252986799b007fa1fc217399a9585
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
sudo dd if=StickLLM-v0.3.9.iso \
  of=/dev/sdX bs=4M status=progress oflag=sync
sudo eject /dev/sdX
```

Optional helper (same `dd` path):

```bash
ISO=StickLLM-v0.3.9.iso ./scripts/flash-linux.sh /dev/sdX
```

## macOS

```bash
diskutil list
ISO=StickLLM-v0.3.9.iso ./scripts/flash-macos.sh /dev/diskN
```

## After flash

1. Eject the stick.
2. Follow [BOOT.md](BOOT.md).
3. First boot can claim free space as `STICKLLM-DATA` for durable model downloads.
   Until that exists, downloads only live in the RAM overlay.
4. After reflashing over a stick that already used an SSD vault blob, use
   Settings → **Find existing vault** / Open existing (see [VAULT.md](VAULT.md)).

Maintainer-only flash tools and lab gates: [MAINTAINER.md](MAINTAINER.md).
