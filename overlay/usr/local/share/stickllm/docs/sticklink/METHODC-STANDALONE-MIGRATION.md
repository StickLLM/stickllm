# Method C standalone migration (approved 2026-11-08)

Operator-approved direction. **Protocol contract is frozen.** Proceed incrementally; report evidence at each milestone.

## Non-negotiables

1. **Wire + UI contract:** `methodc-lte-accept-20261108.1` + `docs/sticklink/APP-MUX-V1.md`. Do not change the phone wire protocol or working join/A0 UI.
2. **Lab is reference only:** keep `sticklink-server/lab-browser-e2e/` as a frozen working reference. Do not redesign transport.
3. **Join HTML** may stay on a **public HTTPS host**. It must not depend on the lab PC and must not require inbound access to the stick. **Cloudflare must not proxy Agent Zero.**
4. **Do not** overwrite `v0.7.2` or modify tag `methodc-lte-accept-20261108.1`.
5. **No** cleanup/deletion pass, protocol redesign, or new transport architecture.

## Final acceptance (definition of done)

A freshly booted StickLLM USB, with the development PC **powered off**, serves Agent Zero to the operator iPhone over LTE through Method C.

## Milestones

### A — Standalone Method C transport (isolated development authorization)

**Goal:** USB works with the lab PC completely offline.

| On stick | Still allowed (not lab PC) |
|----------|----------------------------|
| WebRTC/Noise peer (today: `kiosk_agent_session` logic) | Public HTTPS join host (Worker / Pages / stick-owned tunnel process on USB) |
| App-mux bridge (today: `app_mux_bridge`) → **localhost** Agent Zero | Signalling `wss://link.stickllm.com` |
| `pair.open` / `sl1:` publish into Devices & Pairing | |
| **Isolated development authorization** (lab-grant class; not product security claim) | |

**Prove:**

1. Lab PC powered off (or disconnected) during the session.
2. Phone LTE → Method C → Agent Zero chat (same APP-MUX-V1 behavior).
3. Bootstrap HTTP still returns `a0_via_sticklink_dc_only` for A0 paths (CF join-only).
4. Inventory of packages/services present on the USB image (see inventory doc).

**Out of A:** native VT trusted-device approval, production pairing ceremony, unauthorized-client rejection matrix.

### B — Native trusted-device approval

**Goal:** replace temporary development authorization with native trusted-device approval and production pairing.

**Prove:** repeat Milestone A tests **plus** rejection of unauthorized clients.

## Implementation order (A)

1. Inventory runtime deps (packages, units, startup) — **this cycle**.
2. Port peer + mux bridge into StickLLM overlay/runtime; A0 upstream = loopback (no SSH to self).
3. Stick publishes `sl1:` / join URL into `/run/stickllm/` (no lab `run_phone_join_lab` publisher).
4. Host join static assets on public HTTPS independent of lab PC.
5. Bake a **new** TEST ISO name (not `v0.7.2`); VM boot test; then hotfix/HW on USB.

## Evidence log

| Date | Milestone | Evidence |
|------|-----------|----------|
| 2026-11-08 | Contract | Tag `methodc-lte-accept-20261108.1` → `860ea3ccd6ed1b5bee6c587317eba1435420f646`; APP-MUX-V1 concurrency 8 / gzip |
| 2026-11-08 | Pre-A lab | Operator: iPhone LTE Method C accepted against lab-assisted path |
| 2026-11-08 | A start | Plan + inventory docs; lab tree retained; known-good tag not moved |
| 2026-11-08 | A scaffold | Stick overlay: `methodc_peer.py`, `app_mux_bridge.py`, `stickllm-methodc-peer` unit/bin; requirements pins; **aiortc still missing on live USB**; public join host not deployed |

## Explicit non-goals this migration

- Changing `sl1:` / Noise / app-mux message types
- DERP-as-browser-media claims without ICE evidence
- LAN/desktop pairing (ISS-033) unless required for B
- Reworking join UI beyond host placement
