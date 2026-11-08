# Cloudflare design vs Canadian data residency

**Decision (2026-11-07):** Canadian-only signalling *metadata* residency is **not**
a requirement. Keep the Cloudflare Workers + Durable Objects + D1 design.
Canadian media path stays on `relay-tor1` (Luna Node, Toronto). Preserve
portability (Hono / portable signalling interfaces) so signalling can move to a
Canadian VPS later if policy changes. No Go/SQLite rewrite now. No new VPS.

This removes the residency blocker for design/lab work. It does **not**
authorise Cloudflare deploy, spend, DNS changes, or live relay admission changes.

## What stays in Canada

| Component | Location |
|---|---|
| DERP / STUN relay | `relay-tor1.stickllm.com` (Toronto); DNS grey-cloud |
| Noise / WebRTC media (after pair) | P2P or via Canadian DERP (ciphertext + routing ids) |

## What may live on Cloudflare (accepted)

| Surface | Notes |
|---|---|
| D1 device/home/audit rows | No Canada jurisdiction exists; placement may be US/EU/global |
| Durable Objects (Home/Router/Limiter/Feed) | Same; optional `us`/`eu` pin is intentional placement, not CA |
| Worker edge + WS signalling | Global unless Regional Services added later |
| DNS for `stickllm.com` | Names only |

## Portability (keep)

- Worker code is Hono-oriented; room/state behind DO bindings that can be swapped
  for an in-process Map + SQLite on a VPS (see `HOSTING-OPTIONS.md`).
- Clients take signalling base URL and relay list from config / `welcome`, not
  hard-coded CF hostnames in the Noise path.
- `RELAYS` var already points at Toronto `relay-tor1`; moving signalling later
  does not require moving the relay.

## Still gated (separate approval)

- `wrangler d1 create` / remote migrations / `wrangler deploy` / Workers Paid
- Custom hostname `link.stickllm.com`
- Replacing deny-all `derp-admit` with `sticklink-admit` on relay-tor1
