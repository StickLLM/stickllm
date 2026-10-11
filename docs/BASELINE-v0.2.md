# StickLLM shipping baseline (v0.2)

## Golden ship (immutable)

- **Samsung Type-C USB** — golden runtime. Never wipe for experiments.
- Drive ISO: `stickllm-amd-rtx3090-v0.2.hybrid.iso` (volume id `STICKLLM`)
- **SHA-256:** `4914087d502d13327dbbd9196c9a4a7df46ee079d423ff4b0bc6280e1c7b1a48`
- Local copy: `out/stickllm-amd-rtx3090.hybrid.iso` (must match that hash)
- Git tag **`v0.2.0`** → commit **`c63fadc`** (branch `stickllm-v0.2-base`)

Do **not** retag, rewrite checksums, or overwrite the Drive / Samsung v0.2 artifact.

## Local restore checkpoint (v0.2.1)

Separate from Drive golden — use when you need Local browser + keyboard on NVIDIA:

| | |
|---|---|
| Tag | `v0.2.1-local-nvidia-kbd` |
| ISO dir | `out/v0.2.1-local-nvidia-kbd/` |
| ISO file | `stickllm-amd-rtx3090-v0.2-local-nvidia-kbd.hybrid.iso` |
| SHA-256 | `9F665ACAA0D60B9DE822781A3A3A3F56C6C4924536E677599C09DBC8D339A1FC` |
| Checksum file | `checksums/v0.2-local-nvidia-kbd.sha256` |

```bash
git checkout v0.2.1-local-nvidia-kbd
```

Park unfinished experiments on `wip/…` branches. Do not treat them as shipping.

## Flash other sticks

Prefer `dd`/Rufus DD of a **hash-verified** hybrid ISO onto a spare stick (e.g. VendorCo).  
Do not flash NVMe or backup drives. Do not overwrite Samsung golden when cloning outward.

Flash helpers refuse without screenshot proof (`out/ISO-READY.txt` with `SCREENSHOT_PROOF=PASS`). See [FLASH.md](FLASH.md).

## Boot back to the pair screen

1. Plug StickLLM USB (Samsung golden or a stick flashed from a verified ISO).
2. Firmware: USB boot, **Secure Boot off** ([BOOT.md](BOOT.md)).
3. Menu → Server or Term → wait for console **pair code** / READY.
4. Open `http://<lan-ip>/` and enter the pair code.
