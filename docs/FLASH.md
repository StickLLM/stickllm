# Flashing StickLLM to USB

**Warning:** Flashing a hybrid ISO **erases** the target USB. Confirm the device
node / disk number before writing.

## Which ISO?

| Image | Path | Checksum |
|---|---|---|
| **Current ship (N) v0.3.6** | Drive `stickllm-amd-rtx3090-v0.3.6.hybrid.iso` or `out/v0.3.6/…` | [`checksums/v0.3.6.sha256`](../checksums/v0.3.6.sha256) → `fb559d9f…` |
| **N-1 v0.3.0** | `out/v0.3.0/stickllm-amd-rtx3090-v0.3-apiready.hybrid.iso` | [`checksums/v0.3.sha256`](../checksums/v0.3.sha256) |
| **Drive golden v0.2** | Drive `stickllm-amd-rtx3090-v0.2.hybrid.iso` | [`checksums/v0.2.sha256`](../checksums/v0.2.sha256) |
| **Local checkpoint** | `out/v0.2.1-local-nvidia-kbd/stickllm-amd-rtx3090-v0.2-local-nvidia-kbd.hybrid.iso` | [`checksums/v0.2-local-nvidia-kbd.sha256`](../checksums/v0.2-local-nvidia-kbd.sha256) |

**Do not flash `v0.3.5`** — truncated/broken (GRUB loops). Use **v0.3.6**.

Verify SHA-256 before every flash. Never overwrite the Samsung / Drive **v0.2** golden or Drive **v0.3.6** with a different digest under the same name.

Google Drive folder (ISOs over the 2 GB GitHub limit): same StickLLM-releases share as prior ships — see [README.md](../README.md).

## Screenshot proof gate

Helpers under `scripts/flash-*.ps1|sh` refuse unless:

- `out/ISO-READY.txt` exists with `SCREENSHOT_PROOF=PASS`
- Listed screendump PNG paths exist
- `out/ISO-NOT-READY.txt` is absent

Serial-only boot is not enough. See [HW-BOOT-CHECKLIST.md](HW-BOOT-CHECKLIST.md).

## Linux

```bash
lsblk -d -o NAME,SIZE,MODEL,TRAN
# Example — REPLACE sdX and pick the ISO you verified
sudo wipefs -a /dev/sdX
sudo dd if=out/v0.3.6/stickllm-amd-rtx3090-v0.3.6.hybrid.iso \
  of=/dev/sdX bs=4M status=progress oflag=sync
sudo eject /dev/sdX
```

```bash
ISO=out/v0.3.6/stickllm-amd-rtx3090-v0.3.6.hybrid.iso \
  ./scripts/flash-linux.sh /dev/sdX
```

## macOS

```bash
diskutil list
ISO=out/v0.3.6/stickllm-amd-rtx3090-v0.3.6.hybrid.iso \
  ./scripts/flash-macos.sh /dev/diskN
```

## Windows (preferred)

Windows often shows **no drive letter** after an isohybrid flash; the disk is still
there — confirm with disk number / size / bus (Get-Disk), not Explorer.

1. **Preferred:** elevated `C:\Python314\python.exe` + `out/safe-flash-samsung-auth.py`
   (Clear-Disk + FSCTL lock/dismount + WriteFile). Proven FLASH_OK path.
2. **Fallback:** [Rufus](https://rufus.ie/) in **DD Image** mode with a hash-verified ISO.

Avoid naive PowerShell `FileStream` raw write (Access Denied even when elevated)
and `Set-Disk -IsOffline` on removable Samsung sticks.

Or (legacy helper; prefers remountable letter):

```powershell
.\scripts\flash-windows.ps1 `
  -Iso .\out\v0.3.6\stickllm-amd-rtx3090-v0.3.6.hybrid.iso `
  -DriveLetter E
```

The helper refuses non-removable volumes and requires typing `FLASH`.

## After flash

1. Eject the stick.
2. Follow [BOOT.md](BOOT.md).
3. First boot can claim free space as `STICKLLM-DATA` for durable model downloads.
   Until that exists, downloads only live in the RAM overlay.
4. After reflashing over a stick that already used an SSD vault blob, use
   Settings → **Find existing vault** / Open existing (see [VAULT.md](VAULT.md)).
