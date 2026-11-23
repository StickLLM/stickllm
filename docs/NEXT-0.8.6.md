# Pending for v0.8.6

Post-**v0.8.5** punch list. Shipping tag/ISO must be a **new** name
(`v0.8.6` / `StickLLM-v0.8.6.iso`) — never overwrite `v0.8.5`
(`a7555511…`).

Tracked: [ISS-039](../ISSUES.md)–[ISS-043](../ISSUES.md). Carry notes in
[NEXT-0.8.5.md](NEXT-0.8.5.md).

## Must bake

| # | Item | Status | Notes |
|---|------|--------|-------|
| **MS1** | Minesweeper intermittent LAN open (ISS-039) | In tree → bake | Desk pair gate + apps-session + iframe 401 retry + sequential scripts + `__stickllmMsReady`. |
| **AZ1** | Agent Zero work folder in Files (ISS-040) | In tree → bake | Files root **Agent Zero** → `vault/addons/agent-zero/work`. |
| **NI1** | NInfer Models path + Set-default copy (ISS-041) | In tree → bake | Shared models dir; engine-filtered Models; download + Activate; no auto `qwen38-27b` pin. |
| **NI2** | ACTIVE_ENGINE path collision (ISS-042) | In tree → bake | `STICKLLM_ACTIVE_ENGINE_FILE`. |
| **NI3** | A0 chat naming on NInfer (ISS-043) | In tree → bake | Top-level `enable_thinking: false`. |

## After flash

- Set default → NInfer → Models shows NInfer catalog → Download → Activate → chat/:8080.
- Minesweeper opens reliably from LAN paired browser.
- Files → Agent Zero shows A0 workdir artifacts.
