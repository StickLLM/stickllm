# Phase 1 deploy report — 2026-11-07

**Approved and executed.** Relay deny-all **unchanged**. Phases 2–4 not started.

## Resources created

| Resource | Value |
|---|---|
| Account | `83ead3dd06c02e0011d009fb1cc13e5f` |
| D1 `sticklink` | `db77321c-ea7b-4bf0-8cc7-2b28cca79cb1` (region ENAM) |
| Migrations | `0001_init.sql`, `0002_dev_auth_audit.sql` applied remote |
| Worker | `sticklink-signalling` version `ca851518-27de-44ff-993a-b1ebacf3fcff` |
| workers.dev subdomain | registered as `stickllm` |
| Public base (preferred) | **`https://link.stickllm.com`** (Workers custom domain; attached when workers.dev TLS was initially failing) |
| workers.dev URL | `https://sticklink-signalling.stickllm.workers.dev` — **200** after brief provision lag |
| Cron | `17 * * * *` |
| `SIGNING_KID` | `prod-1` |
| Signing pub (public) | `B5FJ-W72teNI4hB-5IPB6iuEKdLGCB4YAeyubXPeoLk` |

## Secrets set (names only)

`IP_PEPPER`, `SIGNING_KEY`, `RELAY_TOKENS` — offline files under `C:\Users\peter\sticklink-secrets\` (not in repo). Also `admit-token` / `admit-keys` for Phase 2.

## Smoke results

| Check | Result |
|---|---|
| `GET https://link.stickllm.com/healthz` | **200** `ok` |
| `GET /v1/keys` | **200** kid=`prod-1` |
| `GET /v1/relay/allowlist` no auth | **401** |
| `GET /v1/relay/allowlist?rg=tor1` + Bearer | **200** signed envelope |
| WSS hello/ready (lab stick) | **PASS** home match |
| Relay `derp-admit` / derper | **not touched** (deny-all remains) |

Lab stick provision (public ids only): `dev=Bk5ca9HJkx88jzJZfzso_A` `home=1zR1vOABsw4zsqStn_9Q2Q` — seed stays under `sticklink-secrets\lab-stick-prov\` offline.

## Cost

**Confirmed 2026-11-07 18:51 EST (dashboard checkout):** Workers Paid Plan **US$5 / month**, subscription **active** (`Purchase complete`). Included allowances match CF list (10M Worker requests, DO 1M requests + 400K GB-s, etc.). Luna Node unchanged.

## Unrelated resources

`instrumentlibrary-*` left untouched.

## Next (not approved)

Phase 2: stage `sticklink-admit` on `127.0.0.1:9109` with `-base https://link.stickllm.com`.
