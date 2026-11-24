# Debian 13 + Experimental tab

**Status:** in current ship **v0.8.8** (NInfer/Strata Set default wired since v0.8.2; later ships added HF token, queue Stop/Resume, context Load guard, etc. — see [CHANGELOG.md](../CHANGELOG.md)).  
**Authority:** Experimental Cancel/Continue only (no master unlock toggle).  
**Never rewrite:** published shipping tags / ISO names under the same name with different contents. Restore slots are **N** / **N-1** only — see [RESTORE.md](RESTORE.md).

NVIDIA firmware / `.run` files / prebuilt patched `nvidia.ko` stay **out of the public git tree**. Helpers clone/fetch upstream **after** Cancel/Continue.

### Branch

Product line: GitHub `main` (tag `v0.8.8` for the ship commit).

### Rolling slots (current)

| Slot | Tag |
| --- | --- |
| **N** | `v0.8.8` |
| **N-1** | `v0.8.7` |

---

## Inventory

| Area | State |
| --- | --- |
| Base OS | **Debian 13 trixie** |
| NVIDIA bake | Still **proprietary** `nvidia-kernel-dkms` (open DKMS failed in lb). CMP unlock **requires nvidia-open** at apply time → preflight fails with a clear reason until bake switches or lab installs open. |
| Experimental tab | Settings → Experimental; detect/offer; **wired** download + unlock helpers |
| GPU PCI table | CMP `20c2` / `2082` + RTX 3090 `2204`; 32 GB subsystem `1586` skipped; 3090 Ti out of scope |
| Engines | Strata + NInfer-all via GitHub latest + SHA-256; download + **Set default** swaps :8080 off llama.cpp; shared progress UI/API |
| Future engines | **Project Maya / sfnx** ([johnfink8/sfnx](https://github.com/johnfink8/sfnx) or similar) — **RTX 3090** + Inkling-2-mini (~200 tok/s target); track **ISS-080** (not wired). Upstream 3× V100 demo ≠ StickLLM target. |
| Unlocks | CMP=`stickllm-experimental-unlock` → cmpunlocker; 3090 → gpu-unlock 2.0 (git or curl/tar archive); per-card off-by-default; **no master toggle** |
| Flash | Rufus DD / safe-flash + **full readback** ([FLASH.md](FLASH.md)) |
| Other keep | `firmware-mediatek`; eth-skip WiFi when Ethernet up; StickLink peer-enable; model world-readable perms |

### Helpers

- `/usr/local/bin/stickllm-experimental-engine` — `--i-understand --engine strata|ninfer-all`
- `/usr/local/bin/stickllm-experimental-unlock` — `--i-understand apply|disable --path cmpunlocker|gpu_unlock --bus BDF`
- Lib: `/usr/local/lib/stickllm_experimental.py`

User walkthrough (Models + Load): [NINFER.md](NINFER.md). USB DATA/settings: [USB-LAYOUT.md](USB-LAYOUT.md).

### How to use (after NInfer / Strata download)

1. **Settings → Experimental → Engine downloads** — row shows **Installed** (tag + size) when files exist under `/var/lib/stickllm/experimental/engines/<engine>/<tag>/` (marker `stickllm-download.json`).
2. **Set default** — Confirm. Stops `stickllm-llama`, extracts the engine if needed, starts `stickllm-exp-engine.service` on `127.0.0.1:8080`. Chat, health, and Agent Zero use that OpenAI-compatible port.
3. **Use llama.cpp** — appears when an Experimental engine is active; Confirm restores llama-server.
4. **Re-download…** — optional re-fetch (Confirm). Does not switch engines by itself.
5. **NInfer models** — NInfer does **not** load StickLLM GGUF weights. **v0.8.6 ([ISS-041](../ISSUES.md)):** after Set default, open **Models**, download a **compatible** NInfer profile into the **same models directory** as GGUF, then **Activate**. No hard-coded auto weight. Serve refuses to start until a profile is selected and present on disk. GGUF **Activate** applies again only after restoring llama.cpp.
6. **Strata** — AppImage extract + CUDA engine; driver &lt; 580 uses CUDA 12 pack. May use a local GGUF or download a Strata model on first start.
7. **Reboot** — not required for download/status/set-default. Unlock apply still needs reboot when used.

---

## Future (not wired)

- **Project Maya / sfnx** — https://github.com/johnfink8/sfnx (or similar) — Experimental offer for **RTX 3090 + Inkling-2-mini** (~200 tok/s) — ISS-080. Upstream 3× V100 writeup is not the StickLLM hardware story. Evaluate on lab 3090 before UI download row.

## Still blocked / lab follow-up

1. **CMP unlock on this bake** — needs `nvidia-open` + allowlisted driver (prefer `615.71.09`; refuse `615.78.08`). Proprietary `nvidia-kernel-dkms` → preflight fails with clear reason.
2. **Live mixed-host test** (2× 3090 + CMP) — apply gpu-unlock BDFs + cmpunlocker coexistence; cold reboot verify.
3. **Legal fetch** — NVIDIA firmware for gpu-unlock build downloads at install time (NOTICE.md); not redistributed in StickLLM git/ISO.
4. StickDroid keep-pins APK and StickLink Worker cloud remain **outside** the ISO.
5. NInfer Models UX ships in v0.8.6+ — walkthrough [NINFER.md](NINFER.md).
