# Debian 13 + Experimental tab — **v0.8.0** (shipped)

**Status:** cut as **`v0.8.0`** → `out/v0.8.0/StickLLM-v0.8.0.iso` + `checksums/v0.8.0.sha256`.  
**Authority:** `C:\Users\peter\stickllm\GROK-GPU-UNLOCK-HANDOFF.md` (21 Nov 2026) + Nink voice refinements.  
**Never rewrite:** `v0.7.8`, or golden `v0.2.0`.

This reverses the **3 Nov 2026** decision that left GPU unlocks / special drivers / alternative engines as community add-ons. StickLLM ships **detection, UI, and opt-in installer stubs** with the safety rules below. NVIDIA firmware / `.run` files / prebuilt patched `nvidia.ko` stay **out of the public git tree**; download only after Cancel/Continue (apply paths still scaffolding).

### Branch

`release/v0.8.0` (from StickLink + Experimental WIP on top of `release/v0.7.8`).

### Rolling slots after v0.8.0

| Slot | Tag |
| --- | --- |
| **N** | `v0.8.0` |
| **N-1** | `v0.7.8` |
| **Golden** | `v0.2.0` (unchanged) |

See [RESTORE.md](RESTORE.md).

---

## Inventory

| Area | State |
| --- | --- |
| Base OS | **Debian 13 trixie** (`live-build/archives/debian.list.*`, `docker-build-live.sh --distribution trixie`) |
| NVIDIA | `nvidia-open-kernel-dkms` (+ driver userspace); no blobs in git |
| Experimental tab | Settings → Experimental; detect/offer; download/unlock stubs + Cancel/Continue |
| GPU PCI table | CMP `20c2` / `2082` + RTX 3090 `2204` |
| Flash | Rufus DD / safe-flash + **full readback** ([FLASH.md](FLASH.md)) |

---

## Still later (not auto-install)

1. Engine download wiring (Strata / NInfer-all fetch+verify behind Continue).
2. Unlock apply/disable (cmpunlocker + gpu-unlock wrappers, rollback, mixed-host test).
3. StickDroid keep-pins APK and StickLink Worker cloud remain **outside** the ISO.
