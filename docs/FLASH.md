# Flashing StickLLM to USB

**Warning:** Flashing a hybrid ISO **erases** the target USB. Confirm the device
node / disk number before writing.

## Get the ISO

| Image | Where | Checksum |
|---|---|---|
| **Current ship v0.3.6** | [Google Drive](https://drive.google.com/drive/folders/1sTgvoyQi3aU-sauolWd35bKTLGynNEd-?usp=sharing) — `stickllm-amd-rtx3090-v0.3.6.hybrid.iso` | [`checksums/v0.3.6.sha256`](../checksums/v0.3.6.sha256) → `fb559d9f…` |

**Do not flash `v0.3.5`** — truncated/broken. Use **v0.3.6**.

Release notes: [v0.3.6](https://github.com/StickLLM/stickllm/releases/tag/v0.3.6).

## Verify SHA-256

```powershell
(Get-FileHash .\stickllm-amd-rtx3090-v0.3.6.hybrid.iso -Algorithm SHA256).Hash
# expect FB559D9F0CC5182406F0851F09C1E28C302F911C01B46CAC545EF4D920E1A43D
```

```bash
sha256sum stickllm-amd-rtx3090-v0.3.6.hybrid.iso
# expect fb559d9f0cc5182406f0851f09c1e28c302f911c01b46cac545ef4d920e1a43d
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
sudo dd if=stickllm-amd-rtx3090-v0.3.6.hybrid.iso \
  of=/dev/sdX bs=4M status=progress oflag=sync
sudo eject /dev/sdX
```

Optional helper (same `dd` path):

```bash
ISO=stickllm-amd-rtx3090-v0.3.6.hybrid.iso ./scripts/flash-linux.sh /dev/sdX
```

## macOS

```bash
diskutil list
ISO=stickllm-amd-rtx3090-v0.3.6.hybrid.iso ./scripts/flash-macos.sh /dev/diskN
```

## After flash

1. Eject the stick.
2. Follow [BOOT.md](BOOT.md).
3. First boot can claim free space as `STICKLLM-DATA` for durable model downloads.
   Until that exists, downloads only live in the RAM overlay.
4. After reflashing over a stick that already used an SSD vault blob, use
   Settings → **Find existing vault** / Open existing (see [VAULT.md](VAULT.md)).

Maintainer-only flash tools and lab gates: [MAINTAINER.md](MAINTAINER.md).
