# Pending for v0.8.4

Post-**v0.8.3** punch list. Shipping tag/ISO must be a **new** name
(`v0.8.4` / `StickLLM-v0.8.4.iso`) — never overwrite `v0.8.3` (`26ceba9f…`).

## Must bake (regression from v0.8.3) — do not leave these off

| # | Item | Status | Notes |
|---|------|--------|-------|
| **1** | **CUDA sonames at boot (no Vulkan on NVIDIA)** | In tree → commit before bake | v0.8.3 ISO lacked `.so.1` / `libggml-cuda.so.0` and never created them at boot → Vulkan on RTX. Fix: `ensure_cuda_sonames` in `stickllm-pick-gpus` + `build-llama-server.sh` always-link-on-skip. Verify: health `backend=cuda`. Live: HOTFIX §1 #1 / `out/_hotfix_cuda_boot_path.py`. |
| **2** | **`find_mmproj` family match** (wrong projector → VL load fail) | In 0.8.3 tree; **re-verify on every flash** | Lab hotfix fixed “loads wrong mmproj” (e.g. VL-3B leftover for VL-8B/4B). Must stay in ISO (`_mmproj_family_key` / `find_mmproj` in `stickllm-control`). Unit: `tests/test_v053.py::test_c_find_mmproj_prefers_matching_family`. Verify after Activate: llama cmdline `--mmproj` matches model family. Live: HOTFIX §1 #2 / `out/_hotfix_mmproj_and_probe.py`. |
| **3** | **StickLink app-mux large POST bodies** (StickDroid image send ~250 KiB stall ~180 s) | In tree (`c9ba382`); **counts only after fresh-flash verify** | Stick `app_mux_bridge.py`: seq reassembly, orphan chunks, finish on `body_len`, `CHUNK=24KiB`. Unit: `tests/test_app_mux_large_body.py` (250 KiB + 2 MiB &lt; 5 s). Live worker: private `5b074d0` (do not drop sess.frames on rate). StickDroid 0.3.9+: pacing/CHUNK. **Do not call fixed until bake+flash passes this test on a clean stick.** |
| **4** | **Method C peer + keepalive** (in-tree `methodc_peer.py`) | **Baked** in `StickLLM-v0.8.4.iso` (`methodc-noise-keep-20261121.3`) | Without peer/keepalive, phone StickLink will **not** stay connected on a clean flash (needs live hotfix). Bake includes overlay peer + `methodc-peer.env` + `stickllm-methodc-peer.service`. Verify after boot: peer running, stamp `methodc-noise-keep*`, idle phone stays `connected`. |

## Already expected from v0.8.3


Rest of vision / Terminal / UI punch list from [NEXT-0.8.3.md](NEXT-0.8.3.md) — verify on flash; hotfix only if verify fails.
