# Method C browser E2E vs live signalling — 2026-11-07

**PASS.** Lab stick + Playwright browser against `wss://link.stickllm.com/v1/ws` (no local wrangler).

## Proven

| Check | Result |
|---|---|
| Method C mailbox (`pair.open` / join) | **PASS** |
| Noise IKpsk2 pinned over DataChannel | **PASS** |
| pair_psk + confirm | **PASS** |
| Chat stream cancel | **PASS** |
| Slot revocation | **PASS** |

Harness: `sticklink-server/lab-browser-e2e/run_e2e_live.py`  
Artifact: `…/state/results/e2e-live-report.json`

## Lab caveats (unchanged)

- **LAB BYPASS:** no native VT / `approve_local` — not for shipping (LAB-BYPASS.md).
- Media path here is local WebRTC DC (same host), not forced DERP (DERP force-relay was Phase 4).
- Legacy LAN `stickllm-pair` still shipping default.

## Remaining product

Native VT overlay + kiosk QR UX + HW validate before retiring LAN pair.
