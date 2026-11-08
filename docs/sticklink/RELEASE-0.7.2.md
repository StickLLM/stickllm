# StickLLM v0.7.2 — TEST ISO (lab-assisted Method C preview)

**Artifact class:** TEST bake for hardware acceptance.  
**Do not** treat as final ship until operator HW acceptance passes and tag `v0.7.2` is cut.

## In this TEST bake

- **Devices & Pairing StickLink QR** — kiosk shows the StickLink phone join QR (not the LAN address). Gateway `GET /api/pair/sticklink-join` (+ remint `GET/POST /api/pair/sticklink-join-refresh`); `stickllm-sticklink-join-publish` writes `/run/stickllm/sticklink-join.json`.
- **Method C — lab-assisted preview** — cellular Agent Zero path is **Method C only** (rendezvous → WebRTC → Noise → app-mux DataChannel). Enrolment is **lab-assisted**: a lab join host publishes the public join URL / `sl1:` mailbox into the stick’s Devices & Pairing QR. This is **not** native VT-default enrolment and **not** Phase 2 (peer on stick).
- **SearXNG** preferred engines (Bing / Yahoo / Seznam / Wikipedia) for shared-egress CAPTCHA.
- Known-good Method C tree preserved as tag `methodc-lte-accept-20261108.1` (`860ea3cc…`). Do not move that tag.

## Lab-assisted preview — what that means

| On the stick (this ISO) | Lab-only (not this ISO’s peer stack) |
|-------------------------|--------------------------------------|
| Kiosk UI + StickLink join QR display | Cloudflare **join page only** (HTML/SW/static) |
| Gateway join JSON + remint request API | Method C WebRTC/Noise **peer** + app-mux bridge answering the phone |
| Agent Zero runtime on stick | Trusted-approval / lab grants used by phone-join lab (`sticklink-lab` mint paths) |
| | Join build id `methodc-lte-accept-20261108.1` assets |

See [METHODC-LAB-DEPS-0.7.2.md](METHODC-LAB-DEPS-0.7.2.md).

## Relay / ICE wording (evidence-based)

- **DERP** (`relay-tor1.stickllm.com`) is the StickLink **native-client** relay path (Tailscale derper + admit). Documented in signalling/relay docs.
- **Method C browser lab** advertises STUN (`stun.l.google.com`, `stun.cloudflare.com`, `stun:relay-tor1.stickllm.com:3478`) and may fetch short-lived **elixir-webrtc TURN** credentials for lab ICE config.
- **Lab measured ICE** on the acceptance gate: **direct** (`prflx`/`host`, udp).  
- **Do not claim** “TURN fallback saved the session” or “DERP carried Method C browser media” without a recorded `iceType=relay` (or equivalent) from that session. iPhone LTE path: operator accepted; ICE type on phone = **UNTESTED** in lab instrumentation.

## Known issues (do not block this TEST bake)

- **ISS-033** — LAN / desktop Agent Zero via original pairing is **broken and deferred** (not fixed in 0.7.2).
- **ISS-034** — Lab automation: Send again after a completed response timed out (`AGAIN_OK`); operator LTE chats still succeeded. Open issue.

## Not in this release cycle

- Phase 2: moving WebRTC/Noise peer + app-mux onto stick `sticklinkd`
- Native VT Method C as default enrolment
- Redesign / alternate connection methods
- Final shipping tag `v0.7.2` (cut only after HW acceptance)

## Operator TEST checklist (stop for human)

1. Flash `out/v0.7.2/StickLLM-v0.7.2.iso` (Rufus DD or lab Samsung flasher).
2. Boot to kiosk READY.
3. Devices & Pairing: StickLink QR appears; after ~60s mailbox expiry, **refresh/remint** and confirm a new QR.
4. With lab join publisher running: phone LTE → scan → Method C → Agent Zero chat.
5. Confirm CF serves join only (A0 not over CF).

## Artifacts

| | |
|--|--|
| ISO | `out/v0.7.2/StickLLM-v0.7.2.iso` |
| SHA-256 | `checksums/v0.7.2.sha256` (TEST bake; rewrite only if a new TEST bake replaces this file **before** ship tag) |
| Parked morning pre-Method-C ISO | `out/v0.7.2/StickLLM-v0.7.2-pre-methodc-20261108am.iso` |
| Method C known-good tag | `methodc-lte-accept-20261108.1` |
| Shipping tag `v0.7.2` | **Not created** until HW acceptance |
