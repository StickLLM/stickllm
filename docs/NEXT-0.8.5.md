# Pending for v0.8.5

Post-**v0.8.4** punch list. Shipping tag/ISO must be a **new** name
(`v0.8.5` / `StickLLM-v0.8.5.iso`) — never overwrite `v0.8.4`.

Tracked issues: [ISS-037](../ISSUES.md) (vault Delete + Skip), [ISS-038](../ISSUES.md)
(A0 offline / exec bits; operator checklist #35–37).

## Must bake — ISS-037 Delete vault in setup

| # | Item | Status | Notes |
|---|------|--------|-------|
| **A** | **Delete vault and start fresh** | In tree → bake | Unlock + wizard vault step; Forgot password?; wrong-password path. |
| **B** | **Confirm dialog** | In tree → bake | Checkbox “I understand this erases my vault”; Delete gated; Cancel; confirm above setup z-index. |
| **C** | **Delete implementation** | In tree → bake | `vault_erase_setup` / `stickllm-vault erase-setup` (ERASE_VAULT, no passcode); stops llama/agent; wipes corrupt blobs; clears vault.key + pointers; audit reason. |
| **D** | **After delete → Create or Skip** | In tree → bake | `vault_skipped` in setup.json; Skip finishes Ephemeral; maybeOfferSetupOrUnlock honors skip. |
| **E** | **VM gate** | After flash | Corrupt / wrong×3 / happy-path unlock. |

## Must bake — Agent Zero offline-capable first start (ISS-038)

| # | Item | Status | Notes |
|---|------|--------|-------|
| **1** | **Bake A0 first-start deps into the image** | Deferred | Soft-no-op path used this cut (no digest re-pin). Revisit for a later image rebuild. |
| **2** | **Or soft-no-op offline** | In tree → bake | Entrypoint: framework deps warn-and-return (no uv / no restart); Local TTS RuntimeError soft-fail. |
| **3** | **Preserve docker-graph file modes on USB** | In tree → bake | Hook excludes `/opt/stickllm/docker` from chmod 644; re-asserts overlay `+x` + pyenv python check. `ensure_seeded` chmods DATA overlay2. |
| **4** | **`the_listener` Python** | In tree → bake | Entrypoint supervisord patch: `/usr/bin/python3`. |
| **5** | **Offline VM gate** | After flash | No NIC: `/api/health` **200 within 60 s**. |

## Lab lessons (do not repeat)

- **“Preload completed” ≠ ready.** That line is from `preload.py` in parallel; uvicorn may still be unbound. Gate on HTTP `/api/health`, not that log line.
- **`stickllm-agent run` always `docker rm -f` + `docker run`.** Runtime installs repeat every start unless baked or skipped offline.
- **Do not leave `run_ui` stopped.** Any lab “unstick” that `supervisorctl stop` / `pkill` must `supervisorctl start run_ui` (or full agent restart) before claiming failure.
