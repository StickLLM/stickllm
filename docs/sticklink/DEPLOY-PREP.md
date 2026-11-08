# Deployment preparation (inventory + auth) — no deploy yet

Authenticated inventory of the Cloudflare account and read-only relay SSH are
required before any deploy approval checkpoint. **Do not paste tokens or private
keys into chat.** Do not create D1 until deploy is approved; keep the
placeholder `database_id` until then and record the real UUID only after
`wrangler d1 create sticklink` succeeds.

## Missing authentication (exact)

### 1. Cloudflare — inventory status (2026-11-07)

`npx wrangler login` completed. `whoami` OK (OAuth as `peter@nink.com`).  
IDs recorded in `CF-INVENTORY-20261107.md`.

**Still missing for full DNS inventory (not blocking Worker/D1 list):**

| Permission | Why |
|---|---|
| **Zone → DNS → Read** on `stickllm.com` | Current OAuth `zone (read)` can load the zone object but `GET …/dns_records` returns **403**. Re-login with DNS read, or a scoped token including DNS Read, to confirm `relay-tor1` grey-cloud / absence of `link`. |

**Still missing before deploy approval (spend/product):**

| Item | Why |
|---|---|
| Workers **Paid** plan confirmed in dashboard | Subscriptions API not readable with this OAuth; Paid needed for reliable DO/D1 |
| First visit to Workers & Pages (or equivalent) | Creates `workers.dev` subdomain (currently absent, API 10007) |

**Do not** run `d1 create` until deploy approval; keep placeholder `database_id`.

### 2. Relay SSH — **blocking read-only service verify**

Documented access: `debian@relay-tor1.stickllm.com` with the existing ed25519
key recorded on **Sticklink’s assistant computer** at `~/.ssh/sticklink_relay`.
That path is **not** assumed to be the offline LAN build box. Do **not** search
other hosts or generate a replacement key.

On this agent machine today:

- `C:\Users\peter\.ssh\sticklink_relay` **absent** (transfer not claimed by this note)

**Missing step:** an operator securely places that existing private key at
`C:\Users\peter\.ssh\sticklink_relay` with restrictive ACLs (never paste into
chat/repo). Then run the read-only checklist in
`docs/sticklink/RELAY-INVENTORY-CHECKLIST.md` (no restarts, no admit cutover).

Keep admission **deny-all** until a **separately approved** cutover. Do not
assume unit names or rollback timing from older docs until inventory captures
the live configuration.

## D1 checkpoint (future approval only)

1. Confirm auth + Workers Paid.
2. `npx wrangler d1 create sticklink` → record returned `database_id`.
3. Replace placeholder in `worker/wrangler.toml`.
4. `npx wrangler d1 migrations apply sticklink --remote`.
5. Secrets + deploy — only under the same approval.

Until then, local tests use `wrangler dev --local` with the placeholder id and
`--persist-to` under an isolated state dir.
