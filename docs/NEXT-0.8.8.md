# v0.8.8 — SHIPPED

**ISO:** `StickLLM-v0.8.8.iso`  
**Checksum:** `c5aa2305461583102beaff7bf227967bd83d89c773badf3e07a958234e96792a` (`checksums/v0.8.8.sha256`)  
**Local:** `out/v0.8.8/StickLLM-v0.8.8.iso` / `E:\stickllm-build\out\v0.8.8\` / `E:\stickllm-isos\`  
**Tag / tree:** release bake including ISS-065 … ISS-073 (see CHANGELOG 0.8.8).

This file is **historical**. Do not add new must-bake rows here — use [NEXT-0.8.9.md](NEXT-0.8.9.md).

## What shipped in the ISO (ISS-065 … ISS-073)

| # | Item | Final |
|---|------|--------|
| **NI7** | NInfer false “loading Qwen2.5” (ISS-065) | Shipped in ISO |
| **NI8** | NInfer HF token on profile download (ISS-066) | Shipped in ISO |
| **CLK2** | Desk timezone from IP geolocation (ISS-067) | Shipped in ISO |
| **NI9** | NInfer download Stop / Resume / Delete (ISS-068) | Shipped in ISO |
| **NI10** | Models false “Downloading Qwen2.5” over NInfer (ISS-069) | Shipped in ISO |
| **ST2** | Download into free RAM + USB persist (ISS-070) | Shipped in ISO |
| **ST3** | RAM spike guard fallocate + soft lock (ISS-071) | Shipped in ISO |
| **TU2** | NInfer Context slider + Load RAM guard (ISS-072) | Shipped in ISO |
| **ST4** | Async USB drain during ram+usb download (ISS-073) | Shipped in ISO |

**Not in `StickLLM-v0.8.7.iso`** (`5e554919…`). Lab hotfixes of 065–070/072 on a v0.8.7 stick were volatile until this bake.
