<!-- Copyright (c) 2026 Nink Inc. All rights reserved. -->
# Deploying sticklink signalling — PLAN ONLY, NOTHING HAS BEEN DONE

**Every step below needs Nink's explicit approval before it runs.** So far nothing has been
deployed, no Cloudflare resource has been created, and the live relay `relay-tor1.stickllm.com`
hasn't been touched.

## 1. What has to exist

| Resource | Command (run only after approval) | Notes |
|---|---|---|
| Cloudflare **Workers Paid** plan on the account | dashboard | US$5/mo minimum. SQLite Durable Objects also run on Workers Free, but the free daily caps make operations *fail*, and failing signalling is worse than paying $5. |
| D1 database `sticklink` | `npx wrangler d1 create sticklink` | Paste the returned id into `worker/wrangler.toml` `database_id` (it's a placeholder now). |
| D1 schema | `npx wrangler d1 migrations apply sticklink --remote` | `worker/migrations/0001_init.sql`, `0002_dev_auth_audit.sql` (device `ak`, audit log) |
| Durable Object classes | created by the first deploy (`[[migrations]] tag="v1"`) | HomeDO, RouterDO, LimiterDO, FeedDO (all SQLite-backed) |
| Secrets | `node scripts/gen-prod-secrets.mjs --out ~/sl-secrets --kid prod-1 --rg tor1`, then `wrangler secret put IP_PEPPER`, `SIGNING_KEY`, `RELAY_TOKENS` from those files | The generator writes 0600 files, refuses to overwrite, and prints only the kid and public key. Keep `~/sl-secrets` offline afterwards. There is **no** device master secret (Q-S1, Nink 2026-10-29). |
| Var | `SIGNING_KID = "prod-1"` in `wrangler.toml` | `FEATURE_SPAKE2_CODE` stays `"0"` |
| Route | custom domain `link.stickllm.com` → the Worker (zone `stickllm.com` must be on Cloudflare) | Or start with `*.workers.dev` for M1, as SIGNALLING-PLAN suggests. |
| Cron | from `wrangler.toml` (`17 * * * *`) | hourly prune |
| Deploy | `npx wrangler deploy` | |
| Devices | The device generates its Ed25519 auth key itself and exports the public key. Then `node scripts/provision.mjs --kind stick\|kvm --ak <b64u pub> --cls … --days … --by <operator> --out …` and `wrangler d1 execute sticklink --remote --file provision.sql` | Output is public only (`<dev>.ids.json`: dev, home). No secret is generated or handled server-side. The SQL includes an `ops` audit row. |
| Device lifecycle | `node scripts/devctl.mjs disable\|enable\|setak …` → SQL for review → `wrangler d1 execute … --file` | `disable` also withdraws the device's relay permits; `setak` replaces a **lost** key (normal rotation is in-band `auth.rotate`). All audited. |

## 2. Cost estimate

| Item | Monthly |
|---|---|
| Workers Paid (includes 10M Worker requests, 1M DO requests, 400k GB-s DO duration, D1 and DO SQLite allowances) | **US$5.00** |
| Expected extra at pilot scale (≤ 100 homes): WebSocket messages bill 20:1, the hibernation API means idle sockets cost no duration, and `{"t":"ping"}` is auto-answered | ~US$0 |
| Luna Node relay VPS (existing, unchanged) | US$3.50 (already being paid) |
| **New spend** | **≈ US$5/mo** |

Pricing checked on 2026-10-29 at developers.cloudflare.com/durable-objects/platform/pricing (last updated Oct 18, 2026).
What would cost more: clients that don't hibernate (none in this design), or >1M DO requests/month (about 20M WS messages), at $0.15 per extra million.

## 3. Relay change (relay-tor1) — replaces the deny-all `derp-admit` stub

Everything happens on the same port, so **derper's flags and `/etc/default/derper` don't change**
(`DERP_VERIFY_URL=http://127.0.0.1:9099/derp/admit`, `-verify-client-url-fail-open=false`).

1. Build: `cd sidecar && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o sticklink-admit ./cmd/sticklink-admit`
2. Copy to `/usr/local/bin/sticklink-admit` (root, 0755).
3. `/etc/sticklink/admit-token` (root, 0600): the `tor1` relay token from `gen-prod-secrets.mjs`.
   `/etc/sticklink/admit-keys`: the `prod-1 <pubkey>` line (`admit-keys` from the generator, which is public).
4. Install `sidecar/deploy/sticklink-admit.service` with `-base https://link.stickllm.com -region tor1`.
   It needs **outbound HTTPS**. The nftables policy doesn't restrict outbound, and the new unit doesn't use the stub's
   `IPAddressDeny=any`.
5. In `derper.service`, change `Wants=`/`After=` from `derp-admit.service` to `sticklink-admit.service`.
6. In one maintenance window (both services bind 127.0.0.1:9099, and derper denies everyone in the gap):
   `systemctl daemon-reload && systemctl disable --now derp-admit && systemctl enable --now sticklink-admit`,
   check that `curl -s 127.0.0.1:9099/healthz` gives `ok` (503 means it hasn't pulled the allowlist yet), then `systemctl restart derper`.
7. Check: a registered key from a test device gets through, and a fresh key is rejected
   (`integration/derpprobe`, built as in `integration/run.sh`).

**Rollback** (about a minute, and fails closed throughout): `systemctl disable --now sticklink-admit && systemctl enable --now derp-admit`,
restore derper's `Wants/After`, then `systemctl restart derper`. The relay is back to deny-all.

Behaviour to accept (OPEN-QUESTIONS Q-R6, Q-S6): if the Worker is unreachable for more than 15 min the relay
admits **no** new clients. A revoked key is refused on its next connection, but derper can't kill a
DERP session that is already open.

## 4. Order for M1

1. Nink approves this plan, the cost, and the Q-items marked "needs Nink".
2. Cloudflare: Workers Paid, D1 create, migrations, secrets, deploy to `*.workers.dev` first.
3. Provision a test stick and KVM, then run `integration/e2e.mjs` against the deployed URL (with base and token adjusted).
4. Relay change (§3) in a quiet window, then the probe test.
5. Add the custom domain `link.stickllm.com` and repoint `-base`.

## 5. Approval checklist

- [ ] Cloudflare Workers Paid ($5/mo) on the account that holds `stickllm.com`
- [ ] Create D1 `sticklink`, run the migration, deploy the Worker, set four secrets
- [ ] Route `link.stickllm.com`
- [ ] Relay: install `sticklink-admit`, retire `derp-admit` (rollback above)
- [ ] Decisions: Q-N1, Q-N5, Q-S1, Q-S6, Q-S12, Q-R6
