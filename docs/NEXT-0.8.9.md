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
| **VL1** | Vault locked ≠ block A0 / core StickLLM (ISS-076) | Agreed → implement → **bake v0.8.9** | Design: lock = ephemeral only (no durable chats/secrets). Unlock = vault save / HF in settings / durable A0. Tree still hard-gates dockerd/A0 on vault mount (`docker_may_start`, systemd ConditionPath, UI “Unlock vault”). Separate from DU1/AZ1. |
| **DU1** | Dual-USB vault unlock → A0 `settings_missing` (ISS-074) | Agreed → implement → **bake v0.8.9** | Boot ISO stick + second-slot DATA/settings: vault unlocks, StickLink pairs, A0 503 `agent_not_running`. Open settings on DATA disk (or ensure boot settings); honest UI when settings missing. |
| **AZ1** | Corrupt USB A0 docker graph `/bin/bash` missing (ISS-075) | Agreed → implement → **bake v0.8.9** | Lab manually reseeded (moved corrupt graph, `ensure-seeded`) → A0 HTTP 200. Product smoke+auto-reseed + UI still to land. |
| **TU3** | Optional Advanced VRAM-ceiling warn for NInfer high ctx (follow-on from ISS-072 lab) | Agreed → implement → **bake v0.8.9** | Host MemAvailable guard still passes 128K on 3090/27B while VRAM fails (~22 GiB used at 96K; 128K exits). Warn near VRAM ceiling so refuse copy is not only host-RAM. |

## Later (not must-bake for v0.8.9)

| # | Item | Status | Notes |
|---|------|--------|-------|
| **MD1** | Multi-device pairing up to 8 on one stick / shared vault (ISS-077) | Agreed → plan / implement post-0.8.9 | Phase 1: concurrent LAN + StickLink sessions, one vault. Phase 2: admin/roles / separate vaults — open. |
| **CW1** | Phone Chat / Work / A0 (ISS-078) | Agreed → plan / implement post-0.8.9 | Chat = `/api/chat` (old UI); Work = simplified A0; A0 = full. **Explicit Chat→A0 handoff** (send to agent / mode switch; soft suggest OK; auto-escalate later). StickDroid + web client. |
| **WA1** | Phone web client stickllm.com/app (ISS-079) | Agreed → roadmap post-0.8.9 | APK alternative; QR → connect → site. Fix connection/timeouts before calling it shipping. |

## Product rules

**Agreed fixes** → ISSUES + this file + CHANGELOG Unreleased same turn — `.cursor/rules/record-agreed-fixes.mdc`.

**After v0.8.9 ships:** move rows to Closed; start `docs/NEXT-0.8.10.md`.
