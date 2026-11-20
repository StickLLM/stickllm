# Flashing StickLLM to USB

**Warning:** Flashing a hybrid ISO **erases** the target USB. Confirm the device
node / disk number before writing.

## Get the ISO

| Image | Where | Checksum |
|---|---|---|
| **Current image **v0.7.7**.sha256) → `f166caa4…` |

**Hash of record is in this repo** (`checksums/v0.7.7.sha256`). Verify the Drive download against that digest — do not treat a hash only on Drive as authoritative. Previous published ships (`StickLLM-v0.4.2.iso`, `StickLLM-v0.3.9.iso`, `StickLLM-v0.3.8.iso`, …) stay available under their own names — never overwrite those files with different contents.

N-1 restore examples: `StickLLM-v0.7.0.iso` / older Drive ships — see [RESTORE.md](RESTORE.md).

## Verify SHA-256

```powershell
(Get-FileHash .\StickLLM-v0.7.7.iso -Algorithm SHA256).Hash
# expect F166CAA465B708C9D681A52BEC99CD318248DB390D532CDF9AD08FF79B96848E
```

```bash
sha256sum StickLLM-v0.7.7.iso
# expect f166caa465b708c9d681a52bec99cd318248db390d532cdf9ad08ff79b96848e
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
sudo dd if=StickLLM-v0.7.7.iso \
  of=/dev/sdX bs=4M status=progress oflag=sync
sudo eject /dev/sdX
```

Optional helper (same `dd` path):

```bash
ISO=StickLLM-v0.7.7.iso ./scripts/flash-linux.sh /dev/sdX
```

## macOS

```bash
diskutil list
ISO=StickLLM-v0.7.7.iso ./scripts/flash-macos.sh /dev/diskN
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

