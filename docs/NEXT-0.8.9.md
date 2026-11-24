# Pending for v0.8.9

Post-**v0.8.8** punch list. Shipping tag/ISO must be a **new** name
(`v0.8.9` / `StickLLM-v0.8.9.iso`) — never overwrite `v0.8.8`
(`c5aa2305…`).

## Truth (read this first)

| Where | Notes |
|-------|-------|
| **`StickLLM-v0.8.8.iso`** | Contains ISS-065 … ISS-073 |
| **Git tree (Unreleased → v0.8.9)** | New work only |

## Must bake

| # | Item | Status | Notes |
|---|------|--------|-------|
| **TU3** | Optional Advanced VRAM-ceiling warn for NInfer high ctx (follow-on from ISS-072 lab) | Agreed → implement → **bake v0.8.9** | Host MemAvailable guard still passes 128K on 3090/27B while VRAM fails (~22 GiB used at 96K; 128K exits). Warn near VRAM ceiling so refuse copy is not only host-RAM. |

## Product rules

**Agreed fixes** → ISSUES + this file + CHANGELOG Unreleased same turn — `.cursor/rules/record-agreed-fixes.mdc`.

**After v0.8.9 ships:** move rows to Closed; start `docs/NEXT-0.8.10.md`.
