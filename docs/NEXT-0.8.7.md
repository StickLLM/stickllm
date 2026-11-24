# v0.8.7 — SHIPPED

**ISO:** `StickLLM-v0.8.7.iso`  
**Checksum:** `5e55491903c3340f215e730462ec08d4c508ff91aaf8f2ce8710cdb3c448e8aa` (`checksums/v0.8.7.sha256`)  
**Tag / tree:** release bake including ISS-044 … ISS-064 (see CHANGELOG 0.8.7).

This file is **historical**. Do not add new must-bake rows here.

## Post-ship (NOT in this ISO)

Discovered / fixed **after** the v0.8.7 bake → tracked only in **[NEXT-0.8.8.md](NEXT-0.8.8.md)**:

| ISS | Short |
|-----|--------|
| ISS-065 | NInfer false “loading Qwen2.5” |
| ISS-066 | NInfer HF token on profile download |
| ISS-067 | Timezone from IP on first internet |
| ISS-068 | NInfer queue Stop / Resume / Delete |
| ISS-069 | Models “Downloading Qwen2.5” over live NInfer pull |

Lab hotfixes of those on a stick running v0.8.7 are **not** part of this ship. Reflash of this ISO loses them.

## What shipped in the ISO (ISS-044 … ISS-064)

| # | Item | Final |
|---|------|--------|
| **NI4** | NInfer downloads in Downloads queue (ISS-044) | Shipped in ISO |
| **NI5** | NInfer Load wording + status (ISS-045) | Shipped in ISO |
| **NI6** | Engine UX parity pass (ISS-046) | Shipped in ISO (Stop/Resume for official pins incomplete → **ISS-068** on 0.8.8) |
| **SL1** | StickLink Pairing phone… | Shipped in ISO |
| **CLK1** | NTP on Wi‑Fi (ISS-047) | Shipped in ISO (timezone geo → **ISS-067**) |
| **PWR1** | Power off confirm (ISS-048) | Shipped in ISO |
| **SU1** | Setup Open now Loading (ISS-049) | Shipped in ISO |
| **EX1** | Experimental host persist (ISS-050) | Shipped in ISO |
| **DL1** | Soft-gate downloads (ISS-051) | Shipped in ISO |
| **SR1** | Engine-scoped HF search (ISS-052) | Shipped in ISO |
| **ST1** | USB→RAM stage (ISS-053) | Shipped in ISO |
| **CTX1** | NInfer 32K floor (ISS-054) | Shipped in ISO |
| **A01** | A0 id match (ISS-055) | Shipped in ISO |
| **A02** | A0 LiteLLM bridge (ISS-056) | Shipped in ISO |
| **A03** | A0 vision modalities (ISS-057) | Shipped in ISO |
| **TU1** | Tune panel all engines (ISS-058) | Shipped in ISO |
| **HF1** | NInfer HF `.ninfer` search (ISS-059) | Shipped in ISO |
| **LD1** | Sticky Load → ninfer activate (ISS-060) | Shipped in ISO |
| **SL2** | StickLink keepalive under load (ISS-061) | Shipped in ISO |
| **A04** | A0 syncStore NO_HANDLERS (ISS-062) | Shipped in ISO |
| **VI1** | Vision image shrink (ISS-063) | Shipped in ISO |
| **AZF1** | A0 files on phone (ISS-064) | Shipped in ISO |
