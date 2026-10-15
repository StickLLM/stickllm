# Restore policy (N-2)

Keep the **last two recoverable product ships** plus the immutable Drive golden.

| Slot | Tag / name | ISO | Checksum |
|------|------------|-----|----------|
| Golden (forever) | `v0.2.0` | Drive `stickllm-amd-rtx3090-v0.2.hybrid.iso` | `checksums/v0.2.sha256` → `4914087d…` |
| **N-1** | `v0.3.0` | `out/v0.3.0/stickllm-amd-rtx3090-v0.3-apiready.hybrid.iso` | `checksums/v0.3.sha256` → `f3db9113…` |
| **N** (current) | `v0.3.6` | Drive / `out/v0.3.6/stickllm-amd-rtx3090-v0.3.6.hybrid.iso` | `checksums/v0.3.6.sha256` → `fb559d9f…` |

**Do not flash `v0.3.5`** — that ISO is truncated/broken (see `out/v0.3.5/BROKEN-TRUNCATED.txt`). Use **v0.3.6**.

Older tags (`v0.2.1-local-nvidia-kbd`, `v0.3.1`–`v0.3.4`, …) and their `out/` dirs remain recoverable; they are simply outside the rolling N/N-1 window. Never delete them when cutting the next ship.

## ISO naming (future N)

- **Through v0.3.6:** keep historical filenames (`stickllm-amd-rtx3090-v….hybrid.iso`) for restore paths above — do not rename.
- **v0.3.7 and later:** exactly `StickLLM-vX.Y.Z.iso` under `out/vX.Y.Z/` (example: `StickLLM-v0.3.7.iso`; see [BUILD.md](BUILD.md)). When a newer ship becomes **N**, document it with that pattern; leave older rows on their original names.

## Rules

- When cutting **v0.4** (or any next ship): keep **N** and **N-1** tags and `out/` ISO dirs; do not delete or overwrite them.
- Drive **v0.2.0** is outside the rolling window — never retag, rewrite checksum, or replace the Drive artifact.
- Current **v0.3.6** also lives on **Google Drive** (StickLLM-releases folder; GitHub asset limit is 2 GB). Same folder as prior Drive ships — do not invent a new URL.
- New ships get new tag names, new `out/<version>/` dirs, new `StickLLM-vX.Y.Z.iso` filenames, and new `checksums/<version>.sha256` files.

## Restore N (v0.3.6)

```text
git checkout v0.3.6
ISO:      Google Drive stickllm-amd-rtx3090-v0.3.6.hybrid.iso
          (or out/v0.3.6/stickllm-amd-rtx3090-v0.3.6.hybrid.iso)
Checksum: checksums/v0.3.6.sha256
Expect:   FB559D9F0CC5182406F0851F09C1E28C302F911C01B46CAC545EF4D920E1A43D
```

Flash on Windows: elevated `out/safe-flash-samsung-auth.py` (or Rufus DD). See [FLASH.md](FLASH.md).

## Restore N-1 (v0.3.0)

```text
git checkout v0.3.0
ISO:      out/v0.3.0/stickllm-amd-rtx3090-v0.3-apiready.hybrid.iso
Checksum: checksums/v0.3.sha256
Expect:   F3DB91133AE6FD1CAACAFD385A61DA6949064F32AC60045378BE4D69441FC218
```

## Restore golden v0.2.0

```text
git checkout v0.2.0
ISO:      Google Drive stickllm-amd-rtx3090-v0.2.hybrid.iso
Checksum: checksums/v0.2.sha256
Expect:   4914087D502D13327DBBD9196C9A4A7DF46EE079D423FF4B0BC6280E1C7B1A48
```
