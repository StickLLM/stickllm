# Debian 13 + Experimental tab — **v0.8.1**

**Status:** shipping on `release/v0.8.1`.  
**Authority:** `C:\Users\peter\stickllm\GROK-GPU-UNLOCK-HANDOFF.md` (21 Nov 2026) + Nink voice refinements (no master unlock toggle; Cancel/Continue only).  
**Never rewrite:** `v0.8.0`, `v0.7.8`, or golden `v0.2.0`.

NVIDIA firmware / `.run` files / prebuilt patched `nvidia.ko` stay **out of the public git tree**. Helpers clone/fetch upstream **after** Cancel/Continue.

### Branch

`release/v0.8.1`

### Rolling slots after v0.8.1 ships

| Slot | Tag |
| --- | --- |
| **N** | `v0.8.1` |
| **N-1** | `v0.8.0` |
| **Golden** | `v0.2.0` (unchanged) |

---

## Inventory

| Area | State |
| --- | --- |
| Base OS | **Debian 13 trixie** |
| NVIDIA bake | Still **proprietary** `nvidia-kernel-dkms` (open DKMS failed in lb). CMP unlock **requires nvidia-open** at apply time → preflight fails with a clear reason until bake switches or lab installs open. |
| Experimental tab | Settings → Experimental; detect/offer; **wired** download + unlock helpers |
| GPU PCI table | CMP `20c2` / `2082` + RTX 3090 `2204`; 32 GB subsystem `1586` skipped; 3090 Ti out of scope |
| Engines | Strata (Linux AppImage+CUDA / Windows setup) + NInfer-all (Linux Debian 13 / Windows) via GitHub latest + SHA-256 |
| Unlocks | CMP=`stickllm-experimental-unlock` → cmpunlocker; 3090 → gpu-unlock 2.0; per-card off-by-default; **no master toggle** |
| Flash | Rufus DD / safe-flash + **full readback** ([FLASH.md](FLASH.md)) |
| Other keep | `firmware-mediatek`; eth-skip WiFi when Ethernet up; StickLink peer-enable; model world-readable perms |

### Helpers

- `/usr/local/bin/stickllm-experimental-engine` — `--i-understand --engine strata|ninfer-all`
- `/usr/local/bin/stickllm-experimental-unlock` — `--i-understand apply|disable --path cmpunlocker|gpu_unlock --bus BDF`
- Lib: `/usr/local/lib/stickllm_experimental.py`

---

## Still blocked / lab follow-up

1. **CMP unlock on this bake** — needs `nvidia-open` + allowlisted driver (prefer `615.71.09`; refuse `615.78.08`). Proprietary `nvidia-kernel-dkms` → preflight fails with clear reason.
2. **Live mixed-host test** (2× 3090 + CMP) — apply gpu-unlock BDFs + cmpunlocker coexistence; cold reboot verify.
3. **Legal fetch** — NVIDIA firmware for gpu-unlock build downloads at install time (NOTICE.md); not redistributed in StickLLM git/ISO.
4. StickDroid keep-pins APK and StickLink Worker cloud remain **outside** the ISO.
