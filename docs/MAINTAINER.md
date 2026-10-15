# Maintainer notes (not for end users)

Consumer flash path is Rufus DD / `dd` — see [FLASH.md](FLASH.md).
Dev loop: [DEV-WORKFLOW.md](DEV-WORKFLOW.md). Restore slots: [RESTORE.md](RESTORE.md).

## Windows: Samsung Python flasher (lab)

On this workstation, elevated Python + `out/safe-flash-samsung-auth.py`
(Clear-Disk + FSCTL lock/dismount + WriteFile) is a proven FLASH_OK path for
Samsung sticks. It is **not** shipped as a preferred consumer path (the script
lives under `out/`, which is gitignored).

- Prefer Rufus **DD Image** for anyone downloading from Drive.
- No drive letter after isohybrid ≠ missing USB — confirm with Get-Disk.
- Avoid naive PowerShell `FileStream` raw write and `Set-Disk -IsOffline` on
  removable Samsung sticks.

Legacy helper (prefers a remountable letter):

```powershell
.\scripts\flash-windows.ps1 `
  -Iso .\out\v0.3.6\stickllm-amd-rtx3090-v0.3.6.hybrid.iso `
  -DriveLetter E
```

## ISO-READY / screenshot proof gate

Helpers under `scripts/flash-*.ps1|sh` refuse unless:

- `out/ISO-READY.txt` exists with `SCREENSHOT_PROOF=PASS`
- Listed screendump PNG paths exist
- `out/ISO-NOT-READY.txt` is absent

Serial-only boot is not enough. See [HW-BOOT-CHECKLIST.md](HW-BOOT-CHECKLIST.md).

## ISO integrity check

Before flash or publish, builds run `scripts/lib/iso-integrity-check.sh` so
truncated hybrids (e.g. v0.3.5) fail loud. Wired from `docker-build-live.sh`,
patch helpers, and `smoke-iso-verify.sh`.

## Example lab hardware

Development and HW confirm often use an AMD desktop (e.g. ROMED8 board) +
RTX 3090, plus an ASUS laptop for no-NVIDIA / Vulkan checks. That gear is an
**example**, not a product requirement for end users — see [HARDWARE.md](HARDWARE.md).

## Local restore paths

These are **not** public downloads:

| Slot | Tag | Typical local path | Checksum |
|------|-----|--------------------|----------|
| N-1 | `v0.3.0` | `out/v0.3.0/stickllm-amd-rtx3090-v0.3-apiready.hybrid.iso` | `checksums/v0.3.sha256` |
| N (local copy) | `v0.3.6` | `out/v0.3.6/stickllm-amd-rtx3090-v0.3.6.hybrid.iso` | `checksums/v0.3.6.sha256` |
| Checkpoint | `v0.2.1-local-nvidia-kbd` | `out/v0.2.1-local-nvidia-kbd/…` | `checksums/v0.2-local-nvidia-kbd.sha256` |

Public current ship: Drive **v0.3.6** + checksum in git. See [RESTORE.md](RESTORE.md).
