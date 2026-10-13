# Restore policy (N-2)

Keep the **last two recoverable product ships** plus the immutable Drive golden.

| Slot | Tag / name | ISO | Checksum |
|------|------------|-----|----------|
| Golden (forever) | `v0.2.0` | Drive `stickllm-amd-rtx3090-v0.2.hybrid.iso` | `checksums/v0.2.sha256` → `4914087d…` |
| **N-1** | `v0.2.1-local-nvidia-kbd` | `out/v0.2.1-local-nvidia-kbd/stickllm-amd-rtx3090-v0.2-local-nvidia-kbd.hybrid.iso` | `checksums/v0.2-local-nvidia-kbd.sha256` → `9F665ACA…` |
| **N** (current) | `v0.3.0` | `out/v0.3.0/stickllm-amd-rtx3090-v0.3-apiready.hybrid.iso` | `checksums/v0.3.sha256` → `f3db9113…` |

## Rules

- When cutting **v0.4** (or any next ship): keep **N** and **N-1** tags and `out/` ISO dirs; do not delete or overwrite them.
- Drive **v0.2.0** is outside the rolling window — never retag, rewrite checksum, or replace the Drive artifact.
- New ships get new tag names, new `out/<version>/` dirs, and new `checksums/<version>.sha256` files.

## Restore N (v0.3.0)

```text
git checkout v0.3.0
ISO:      out/v0.3.0/stickllm-amd-rtx3090-v0.3-apiready.hybrid.iso
Checksum: checksums/v0.3.sha256
Expect:   F3DB91133AE6FD1CAACAFD385A61DA6949064F32AC60045378BE4D69441FC218
```

## Restore N-1 (v0.2.1-local-nvidia-kbd)

```text
git checkout v0.2.1-local-nvidia-kbd
ISO:      out/v0.2.1-local-nvidia-kbd/stickllm-amd-rtx3090-v0.2-local-nvidia-kbd.hybrid.iso
Checksum: checksums/v0.2-local-nvidia-kbd.sha256
Expect:   9F665ACAA0D60B9DE822781A3A3A3F56C6C4924536E677599C09DBC8D339A1FC
```

## Restore golden v0.2.0

```text
git checkout v0.2.0
ISO:      Google Drive stickllm-amd-rtx3090-v0.2.hybrid.iso
Checksum: checksums/v0.2.sha256
Expect:   4914087D502D13327DBBD9196C9A4A7DF46EE079D423FF4B0BC6280E1C7B1A48
```
