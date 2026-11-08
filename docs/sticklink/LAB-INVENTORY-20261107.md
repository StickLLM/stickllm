# StickLink live inventory (read-only) — 2026-11-07

Scope: authorised read-only probes only. No configuration changes, restarts,
installations, or secret disclosure.

## Branch

- Worktree: `C:\Users\peter\stickllm-sticklink-wt`
- Branch: `feature/sticklink-browser-lab` @ `f244eb4` (`github/main`)
- Original pairing branch preserved: `feature/sticklink-pairing` (untouched)
- StickLLM `release/v0.6.11` worktree and uncommitted files untouched

## Cloudflare signalling

| Check | Result |
|---|---|
| `worker/wrangler.toml` `database_id` | Placeholder `00000000-…` (no D1 created) |
| `DEPLOY.md` | States nothing deployed; no CF resources created |
| `FEATURE_SPAKE2_CODE` | `"0"` (disabled) |
| `RELAYS` var | `relay-tor1.stickllm.com` / STUN 3478 / rg `tor1` |
| DNS `sticklink.stickllm.com` / `signalling.stickllm.com` / `api.stickllm.com` | NXDOMAIN |
| `sticklink-signalling.workers.dev` | NXDOMAIN |
| Local wrangler auth on this host | Absent (no `.wrangler`, `wrangler` not on PATH) |

**Verdict:** Cloudflare Workers signalling is **not deployed**. Read-only remote
inventory of a live Worker/D1/DO is therefore N/A until a future deploy approval.

## relay-tor1.stickllm.com (Canadian DERP)

| Check | Result |
|---|---|
| DNS | A `170.75.167.152`, AAAA `2602:ffb6:4:e3b0:f816:3eff:feb6:d562` |
| TCP 443 | Reachable |
| HTTPS `/` | HTTP 200, `Content-Length: 0`, HSTS, CSP `default-src 'self'`, `X-Frame-Options: DENY` |
| STUN UDP 3478 from this host | No Binding reply (likely host/network UDP filter; not proof derper STUN is down) |
| SSH `debian@relay-tor1` | Host accepts pubkey auth; **all local keys denied** |
| Auth key location (docs) | `/home/box/.ssh/sticklink_relay` on the LAN build box |
| LAN box `192.168.72.22:22` | Unreachable from this host today |
| Relay key in local backups | Not present as a standalone key file; `E:\…\sticklink-relay.tar.gz` is derper install assets only |

**Verdict:** Public face of the Canadian relay is up on 443. Full read-only SSH
inventory (unit status, admit stub vs sticklink-admit, nftables, journal) is
**blocked** until the `sticklink_relay` key is available on this machine or the
LAN box is reachable. No attempt was made to change the host.

## Port source selection

Compared `feature/sticklink-pairing` sticklink tree vs recovered inventory
(`sticklink-inventory-20261107/stickllm-box`):

- 17 files identical, 17 differ (inventory larger/newer), 6 inventory-only
  (`revocation.py`, USB/e2e extras)
- Lab branch ports **inventory** sticklink + vendored `sticklink-server/`
- Legacy LAN `overlay/usr/local/bin/stickllm-pair` on main kept as-is
- Inventory pair CLI saved as `stickllm-pair-sticklink` pending selective merge

## Explicit non-actions

- No `wrangler deploy`, secret put, D1 create, DNS change
- No relay package install, service restart, or nftables edit
- No push / merge to `main` / shipping ISO / real stick
