# Flashing StickLLM to USB

**Warning:** Flashing a hybrid ISO **erases** the target USB. Confirm the device
node / disk number before writing.

## Which ISO?

| Image | Path | Checksum |
|---|---|---|
| **Drive golden v0.2** | `out/stickllm-amd-rtx3090.hybrid.iso` (or Drive download) | [`checksums/v0.2.sha256`](../checksums/v0.2.sha256) |
| **Local checkpoint** | `out/v0.2.1-local-nvidia-kbd/stickllm-amd-rtx3090-v0.2-local-nvidia-kbd.hybrid.iso` | [`checksums/v0.2-local-nvidia-kbd.sha256`](../checksums/v0.2-local-nvidia-kbd.sha256) |

Verify SHA-256 before every flash. Never overwrite the Samsung / Drive **v0.2** golden with a different digest under the same name.

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
sudo dd if=out/v0.2.1-local-nvidia-kbd/stickllm-amd-rtx3090-v0.2-local-nvidia-kbd.hybrid.iso \
  of=/dev/sdX bs=4M status=progress oflag=sync
sudo eject /dev/sdX
```

```bash
ISO=out/v0.2.1-local-nvidia-kbd/stickllm-amd-rtx3090-v0.2-local-nvidia-kbd.hybrid.iso \
  ./scripts/flash-linux.sh /dev/sdX
```

## macOS

```bash
diskutil list
ISO=out/v0.2.1-local-nvidia-kbd/stickllm-amd-rtx3090-v0.2-local-nvidia-kbd.hybrid.iso \
  ./scripts/flash-macos.sh /dev/diskN
```

## Windows (PowerShell as Administrator)

Prefer [Rufus](https://rufus.ie/) in **DD Image** mode with a hash-verified ISO.

Or:

```powershell
.\scripts\flash-windows.ps1 `
  -Iso .\out\v0.2.1-local-nvidia-kbd\stickllm-amd-rtx3090-v0.2-local-nvidia-kbd.hybrid.iso `
  -DriveLetter E
```

The helper refuses non-removable volumes and requires typing `FLASH`.

## After flash

1. Eject the stick.
2. Follow [BOOT.md](BOOT.md).
3. First boot can claim free space as `STICKLLM-DATA` for durable model downloads.
   Until that exists, downloads only live in the RAM overlay.
