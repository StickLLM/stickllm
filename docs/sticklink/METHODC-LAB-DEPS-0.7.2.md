# Method C lab-only dependencies (v0.7.2 TEST)

This document exists so architects and operators do not mistake the lab phone-join host for on-stick Phase 2.

## On-stick (baked in TEST ISO)

- StickLLM kiosk + **Devices & Pairing** StickLink QR UI
- `stickllm-gateway` — `/api/pair/sticklink-join`, remint status/request
- `stickllm-sticklink-join-publish` — copies join JSON into `/run/stickllm/`
- Agent Zero stack as in prior 0.7.x sticks
- StickLink host Python deps (from 0.7.1 line): cryptography / nacl / websockets for `sticklinkd` **presence** — **not** the Method C browser peer for this preview

## Lab-only (required for Method C phone preview today)

| Dependency | Role |
|------------|------|
| `run_phone_join_lab.py` + `agent_proxy_server.py` | Serves join HTML/SW; refuses A0 over bootstrap HTTP |
| Cloudflare quick tunnel | Public **join page only** |
| `kiosk_agent_session.py` | `pair.open` → WebRTC answer + Noise; waits for phone |
| `app_mux_bridge.py` | HTTP/WS ↔ Agent Zero over DC (gzip, concurrency 8) |
| Join assets (`agent_join.html`, SW, mux, perf) | Build id `methodc-lte-accept-20261108.1` |
| Lab provision / home secrets | D1 home + device credentials for signalling |
| **Trusted-approval / lab grant bypass** | Lab mint paths (`sticklink-lab` grant / enabled flag) so the lab peer can drive Agent Zero without the full consumer pairing ceremony — **lab-only; not a product security claim** |
| **WebRTC + Noise peer placement** | On the **lab PC** for this preview — **not** on stick `sticklinkd` (Phase 2 deferred) |
| Optional elixir-webrtc TURN fetch | Lab ICE helper only; see RELEASE note — no claimed TURN-saved session without evidence |

## Explicitly out of scope this cycle

- Phase 2 peer-on-stick
- Claiming DERP carried browser Method C media without evidence
- Fixing LAN/desktop pairing (ISS-033 deferred)
