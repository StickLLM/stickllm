# Cloudflare inventory (read-only) — 2026-11-07

Auth: `npx wrangler whoami` — OAuth logged in as `peter@nink.com`.  
No credentials, tokens, or secrets are recorded here.

## Account

| Field | Value |
|---|---|
| Account name | Peter@nink.com's Account |
| Account ID | `83ead3dd06c02e0011d009fb1cc13e5f` |
| Type | standard |

## Zone `stickllm.com`

| Field | Value |
|---|---|
| Zone ID | `306f7ad2934d6b221ed3818116ac845d` |
| Status | active |
| Plan | Free Website |
| Nameservers | `josephine.ns.cloudflare.com`, `sonny.ns.cloudflare.com` |

## StickLink signalling resources

| Resource | Status |
|---|---|
| Worker `sticklink-signalling` | **Does not exist** (API 10007) |
| D1 databases | **None** (`wrangler d1 list` → `[]`) |
| Durable Object namespaces | **None** |
| Workers custom domains | **None** |
| `workers.dev` subdomain | **Not created** (API 10007: open Workers & Pages once to create) |

`worker/wrangler.toml` still has placeholder `database_id = 00000000-…`. Real D1 UUID only at deploy-approval `wrangler d1 create sticklink`.

## Other resources on this account (unrelated)

| Kind | Name / id | Notes |
|---|---|---|
| Worker | `instrumentlibrary-mailer` | modified 2026-10-20 |
| Pages | `instrumentlibrary` | instrumentlibrary.org |
| KV | `instrumentlibrary-submissions` (`635cb953…`) | |
| R2 | not enabled | API 10042 |

## Permission gap (inventory)

| Needed for | Status |
|---|---|
| Zone Read (`stickllm.com`) | OK — zone ID retrieved |
| Account / Workers / D1 / DO list | OK |
| **Zone DNS Read** | **Missing** — `GET /zones/{id}/dns_records` → HTTP 403 `10000 Authentication error` |

Wrangler OAuth scopes include `zone (read)` but not DNS record listing. To inventory `relay-tor1` grey-cloud / future `link` records without the dashboard, re-auth with DNS Read or create a token that includes **Zone → DNS → Read** for `stickllm.com`.

## Still not done (gated)

- Create D1 / DO / Worker deploy / secrets / Workers Paid confirm
- Create `workers.dev` subdomain or `link.stickllm.com` route
- DNS changes
- Relay SSH read-only (pending local `~/.ssh/sticklink_relay` on this PC)
- Replace deny-all `derp-admit`
