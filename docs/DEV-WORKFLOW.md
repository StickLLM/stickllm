# StickLLM development workflow

Goal: ship features without rebuilding (or patching) an ISO for every tweak.
Hardware validation stays on real sticks (example: 3090 desktop + ASUS laptop).

## Rules

1. **Feature commits on a feature branch** — iterate with normal git commits.
   Do **not** cut a new ISO per change.
2. **Test on a running stick over SSH** — copy updated scripts/services into the
   live system, restart units, read journals. Rebuild an ISO only when the change
   needs **kernel / drivers / packages / initramfs** (or a clean bake for release).
3. **One clean ISO when the batch is done** — `./scripts/build.sh` (live-build in
   Docker only). **Never patch an ISO** (`docker-patch-iso*`, squashfs inject,
   etc.). Shipping artifacts are immutable; new work gets a new `out/<version>/`.
4. **Hand to the user for HW test**. **Do not tag or push** until the user
   confirms hardware. Flash for a named release line is OK when the user
   explicitly asks; tag/push still wait for HW confirm.

## SSH iterate (preferred)

Boot menu **3 Terminal** or **4 Test** (SSH on). From the READY screen note the
random password, then:

```bash
# example: push one script and restart
scp overlay/usr/local/bin/stickllm-pick-gpus stickllm@<ip>:/tmp/
ssh stickllm@<ip> 'sudo install -m 755 /tmp/stickllm-pick-gpus /usr/local/bin/ && sudo systemctl restart stickllm-llama'
ssh stickllm@<ip> 'journalctl -u stickllm-llama -b --no-pager | tail -80'
```

Useful: `stickllm-status`, `nvidia-smi`, `curl -s localhost:8080/health`,
`/run/stickllm/cuda.env`, `llama-server --list-devices`.

## When you must rebuild

| Change | Path |
|---|---|
| Overlay scripts, UI, systemd units | SSH copy + restart (then one clean ISO at batch end) |
| Package list, NVIDIA/Mesa, cryptsetup | Clean `./scripts/build.sh` |
| llama.cpp CUDA / Vulkan / CPU binaries | `STICKLLM_FORCE_LLAMA_BUILD=1 ./scripts/build-llama-server.sh` then clean ISO |
| Kernel / initramfs / live-boot | Clean ISO only |

## Clean release bake

```bash
./scripts/verify-host.sh
./scripts/download-model.sh
./scripts/build-llama-server.sh
./scripts/build.sh
# → out/v0.3.7/StickLLM-v0.3.7.iso + SHA256SUMS
# ISO integrity check runs in-build (reject truncated images like v0.3.5).
```

Optional: `STICKLLM_VERSION=0.4.0 ./scripts/build.sh`. Force llama rebuild only if
binaries missing: `STICKLLM_FORCE_LLAMA_BUILD=1 ./scripts/build.sh`.

**ISO names (v0.3.7+):** exactly `StickLLM-vX.Y.Z.iso` under `out/vX.Y.Z/`.  
Through **v0.3.6**, ships used `stickllm-amd-rtx3090-v….hybrid.iso` — leave those
paths and checksums unchanged. Details: [BUILD.md](BUILD.md).

Preserve N-2 restore slots — see [RESTORE.md](RESTORE.md). Current public **N** is
**v0.3.6** (Drive). **N-1** `v0.3.0` ISO is local/maintainer only. Never overwrite
published checksums or shipping tags. **Do not flash v0.3.5** (truncated).

## After flash

- **Consumers:** Rufus DD or `dd` — [FLASH.md](FLASH.md).
- **Lab Windows:** Rufus first; Samsung Python flasher is maintainer-only — [MAINTAINER.md](MAINTAINER.md).
- No drive letter after isohybrid is normal — the disk is still there.

User runs HW checks. Only after confirm: tag, push, publish checksum. Feature work
that is not kernel/drivers stays on a feature branch: SSH-test first, then one
clean build + QEMU proof + integrity check.
