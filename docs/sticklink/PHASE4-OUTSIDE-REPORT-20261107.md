# Phase 4 report — 2026-11-07

**COMPLETE.** Outside-network `--force-relay` chat over live DERP + `relay.del` re-admit deny.

## Environment

| Item | Value |
|---|---|
| Client host | Peter’s Windows PC (not Sticklink LAN / Luna private net) |
| Public egress | `99.229.9.14` |
| Signalling | `wss://link.stickllm.com/v1/ws` |
| DERP | `https://relay-tor1.stickllm.com/derp` |
| Region | `tor1` |
| Lab stick | `dev=Bk5ca9HJkx88jzJZfzso_A` `home=1zR1vOABsw4zsqStn_9Q2Q` |
| Harness | `sticklink-server/lab-browser-e2e/run_phase4_outside.py` |
| Artifact | `…/lab-browser-e2e/state/phase4/phase4-report.json` |

Both sides `--force-relay` (no UDP candidates / no STUN use). Stick registered both DERP nodekeys (peer is slot-join only; no client device auth).

## Proofs

| Check | Result |
|---|---|
| Stick `relay.reg` + DERP connect | **ok** (`fbb79b07`) |
| Peer DERP connect (after stick registered peer nk) | **ok** (`2aead6fd`) |
| Noise IKpsk2 handshake | **ok** via **derp** (~1.6 s) |
| Echo chat | **31/31** over `derp` only; median RTT **79 ms**; no `udp` path |
| `relay.del` stick + peer nks | **ok** |
| Stick fresh DERP after del | **denied** (`IncompleteReadError` / no ServerInfo) |
| Peer fresh DERP after del | **denied** |
| Never-registered nk | **denied** |

`report.ok` / all `proven.*` flags: **true**.

## Notes

- Admit refresh path exercised: register → connect Allow; `relay.del` → reconnect refuse (existing sessions may linger until close — Q-S6; harness cancelled DERP before re-test).
- WebRTC Method C / ICE `relay`-only was **not** used: derper is not TURN. Phase 4 target is sticklink’s DERP data path (`--force-relay`), which is what Phase 3 admit cutover gates.
- `/v1/keys` pin fetch logged a non-blocking HTTPError on stick; revoked page applied remove-only. Does not affect this DERP proof.
- No relay host / CF / DNS / firewall changes.

## Rollback

None required. Optional: `relay.del` any leftover lab nks; Phase 3 rollback only if locking the relay again.
