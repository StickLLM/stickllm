# StickLink deployment approval plan — 2026-11-07

**Status: PLAN ONLY — do not execute until Nink explicitly approves each phase.**  
Live inventory: [`RELAY-INVENTORY-20261107-LIVE.md`](RELAY-INVENTORY-20261107-LIVE.md) (Sticklink, 18:28–18:29 EST).

Order (mandatory):

1. Cloudflare signalling deploy + smoke — **relay deny-all unchanged**
2. Stage real admit sidecar on **separate** loopback port; prove feed / expiry / revoke / fail-closed
3. Back up exact live config; propose switching derper verify URL (**requires derper restart + interruption approval**)
4. Prove browser forced-relay + revocation from an **outside** network

Preserve: relay identity (`/var/lib/derper/derper.key`), LE certs, nftables, SSH.  
Do not touch unrelated CF resources (`instrumentlibrary-*`).

---

## Confirmed costs (public list prices; account bill still to confirm)

Sources fetched 2026-11-07: [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/) (updated Oct 2, 2026), [Durable Objects pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/) (updated Oct 18, 2026). Currency: **USD**.

| Item | Amount | Included usage (Paid) | Notes |
|---|---|---|---|
| **Workers Paid** (account minimum) | **US$5.00 / month** | 10M Worker requests/mo; 30M CPU-ms/mo; DO: 1M requests/mo + 400k GB-s/mo; SQLite DO storage allowances per CF page | **Required** before reliable DO/D1 signalling (Free hard-fails at daily caps) |
| Worker requests beyond include | +US$0.30 / million | — | WS *upgrade* = 1 request; WS messages on Worker are not billed as requests |
| DO requests beyond include | +US$0.15 / million | WS messages to DO bill **20:1** | Hibernation keeps idle duration ≈ $0 |
| DO duration beyond include | +US$12.50 / million GB-s | — | Avoid without hibernation |
| Luna Node `relay-tor1` m.1s | ~US$3.50 / month | existing | Confirm currency on Luna invoice; **unchanged** by this plan |
| **New spend if Phase 1 approved** | **US$5.00 / mo minimum** | pilot expected within includes | **Not activated until approval** |

**Still need operator confirm in CF dashboard before Phase 1:** this account is (or will be) on Workers Paid, and billing currency is USD on the invoice.

Secrets (names only): `IP_PEPPER`, `SIGNING_KEY`, `RELAY_TOKENS`. Vars: `SIGNING_KID=prod-1`, `RELAYS` (tor1), `FEATURE_SPAKE2_CODE=0`, `MBX_GRACE_S`.

---

## Phase 1 — Cloudflare signalling (deny-all relay untouched)

### Preconditions (approval checklist)

- [ ] Workers Paid enabled / confirmed on account `83ead3dd06c02e0011d009fb1cc13e5f`
- [ ] Workers & Pages visited once so `workers.dev` subdomain exists (or approve `link.stickllm.com` instead)
- [ ] Offline secrets generated (never chat/repo):
  ```bash
  # on operator machine, offline
  cd sticklink-server/worker
  node scripts/gen-prod-secrets.mjs --out ~/sticklink-secrets --kid prod-1 --rg tor1
  ```
- [ ] Explicit approval to create D1 + deploy Worker only (no DNS, no relay)

### Exact commands (after approval)

```bash
cd sticklink-server/worker

# 1) Create D1; record UUID into wrangler.toml database_id (replace placeholder)
npx wrangler d1 create sticklink
# edit wrangler.toml: database_id = "<returned-uuid>"
# set SIGNING_KID = "prod-1" in [vars]

# 2) Schema
npx wrangler d1 migrations apply sticklink --remote

# 3) Secrets (values from ~/sticklink-secrets; never echo)
npx wrangler secret put IP_PEPPER    # paste/file contents of IP_PEPPER
npx wrangler secret put SIGNING_KEY  # paste/file contents of SIGNING_KEY
npx wrangler secret put RELAY_TOKENS # paste/file contents of RELAY_TOKENS

# 4) Deploy script sticklink-signalling (creates DO classes via migration tag v1)
npx wrangler deploy

# 5) Smoke against deployed workers.dev (or custom domain once added)
#    Adjust BASE to the printed workers.dev URL
export SL_BASE="https://sticklink-signalling.<subdomain>.workers.dev"
curl -fsS "$SL_BASE/healthz"
# Run Worker integration suite pointed at remote if available, or:
# node ../integration/e2e.mjs   # with env pointing at $SL_BASE + test devices
```

Provision one lab stick auth public key (public only):

```bash
node scripts/provision.mjs --kind stick --ak <b64u-ed25519-pub> --cls … --days … --by ops --out /tmp/stick-prov
# review SQL, then:
npx wrangler d1 execute sticklink --remote --file /tmp/stick-prov/….sql
```

### Phase 1 rollback

| Situation | Command / action |
|---|---|
| Bad Worker version (after ≥1 good deploy) | `npx wrangler rollback` |
| First deploy only | `npx wrangler delete sticklink-signalling` (DO data gone) |
| Abort | Leave D1 unused; **do not** change relay or DNS |

### Phase 1 success gates

- `/healthz` OK on deployed base  
- Authenticated WSS hello/ready for provisioned stick  
- `relay.reg` → signed allowlist visible at `/v1/relay/allowlist?rg=tor1` with Bearer token  
- **Relay still deny-all:** `derp-admit` on `:9099` unchanged; clients still cannot DERP

---

## Phase 2 — Stage `sticklink-admit` on `127.0.0.1:9109` (derper still on 9099)

Leave `derp-admit.service` running. Do **not** change `/etc/default/derper`.

### Install (after Phase 1 base URL known)

```bash
# build (any amd64 builder)
cd sticklink-server/sidecar
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o sticklink-admit ./cmd/sticklink-admit

# on relay-tor1 (scp binary first)
sudo install -m755 /tmp/sticklink-admit /usr/local/bin/sticklink-admit
sudo mkdir -p /etc/sticklink
sudo install -m600 /tmp/admit-token /etc/sticklink/admit-token   # from gen-prod-secrets
sudo install -m644 /tmp/admit-keys  /etc/sticklink/admit-keys    # kid + pubkey

# install STAGING unit (listen :9109; -base = Phase 1 Worker URL)
# file: sidecar/deploy/sticklink-admit-stage.service
# replace REPLACE_WITH_WORKER_BASE before install
sudo install -m644 /tmp/sticklink-admit-stage.service /etc/systemd/system/sticklink-admit-stage.service
sudo systemctl daemon-reload
sudo systemctl enable --now sticklink-admit-stage.service
```

### Prove (loopback only — no derper switch)

```bash
# health: 503 until first verified doc; then 200 + "ok"
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9109/healthz

# deny unknown key (Allow:false)
curl -sS -X POST http://127.0.0.1:9109/derp/admit \
  -H 'Content-Type: application/json' \
  -d '{"NodePublic":"nodekey:0000000000000000000000000000000000000000000000000000000000000000","Source":"127.0.0.1"}'

# after lab device relay.reg on Worker: Allow:true for that nodekey
# revoke / slot.del / allowlist delta: Allow:false on next POST
# stop Worker or corrupt keys → after doc exp, healthz 503 and admits fail closed
# GET /derp/admit → Allow:false (probe-safe)
```

Also run sidecar unit tests locally (`go test ./internal/admit/...`) covering signed-feed validation, expiry, revocation, fail-closed (already in tree).

### Phase 2 rollback

```bash
sudo systemctl disable --now sticklink-admit-stage.service
# leave /usr/local/bin/sticklink-admit and /etc/sticklink/* in place or remove — derper unaffected
```

**Success gates:** healthz fresh; unknown denied; registered allowed; revoked denied; stale/fail-closed; **derper still uses `:9099` deny-all**.

---

## Phase 3 — Switch derper verify URL (**interruption approval required**)

Changing `DERP_VERIFY_URL` is read by derper **only at process start** → **`systemctl restart derper` is mandatory**. Brief window: new DERP clients fail until restart completes; with fail-open=false, verify URL downtime = deny.

### 3a. Back up exact live configuration (before any edit)

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
BK=/root/sticklink-relay-bak-$TS
sudo mkdir -p "$BK"
sudo cp -a /etc/default/derper "$BK/"
sudo cp -a /etc/systemd/system/derper.service "$BK/"
sudo cp -a /etc/systemd/system/derp-admit.service "$BK/"
sudo cp -a /usr/local/lib/sticklink/derp-admit.py "$BK/"
sudo systemctl cat derper derp-admit > "$BK/systemctl-cat.txt"
sudo systemctl show derper -p FragmentPath -p DropInPaths -p Wants -p After -p Requires -p Environment > "$BK/derper-show.txt"
# Do NOT copy derper.key or certs into chat; optional encrypted offline copy of
# /var/lib/derper/ only if operator policy requires — prefer leave in place.
echo "$BK"
```

### 3b. Cutover proposal (execute only after interruption approval)

Preferred path (matches inventory; keeps verify path `/derp/admit`):

1. Stop staging unit; start production unit on **9099** (swap with stub), **or** retarget staging listen to 9099 after stopping `derp-admit`.
2. Point derper at the real sidecar (URL may stay `http://127.0.0.1:9099/derp/admit` if sidecar takes 9099).
3. Update `derper.service` `Wants=`/`After=` from `derp-admit.service` → `sticklink-admit.service`.
4. Restart derper.

Exact sequence when taking over **9099** (canonical):

```bash
# Install production unit listening on 9099 (sidecar/deploy/sticklink-admit.service)
# with -base https://<worker-base> -region tor1

sudo systemctl disable --now sticklink-admit-stage.service   # free ops attention; :9109 down
sudo systemctl disable --now derp-admit.service
sudo systemctl enable --now sticklink-admit.service          # binds 127.0.0.1:9099
curl -sS http://127.0.0.1:9099/healthz                       # expect ok (or 503 until feed)

# derper.service: Wants=/After= sticklink-admit.service (not derp-admit)
# /etc/default/derper: KEEP
#   DERP_VERIFY_URL=http://127.0.0.1:9099/derp/admit
sudo systemctl daemon-reload
sudo systemctl restart derper    # <<< INTERRUPTION

/usr/local/bin/derper -version   # still 1.104.4
curl -fsS -o /dev/null -w '%{http_code}\n' https://relay-tor1.stickllm.com/
```

**Do not** change: `-hostname`, `-certdir`, `-c /var/lib/derper/derper.key`, ports 443/80/3478, nftables, SSH.

### 3c. Conditional rollback (from live inventory)

```bash
sudo systemctl disable --now sticklink-admit.service
sudo systemctl enable --now derp-admit.service
# restore derper.service Wants=/After= derp-admit.service from $BK
# ensure /etc/default/derper has:
#   DERP_VERIFY_URL=http://127.0.0.1:9099/derp/admit
sudo systemctl daemon-reload
sudo systemctl restart derper    # interruption again

curl -sS -X POST http://127.0.0.1:9099/derp/admit \
  -H 'Content-Type: application/json' \
  -d '{"NodePublic":"nodekey:00","Source":"127.0.0.1"}'
# expect {"Allow": false}
```

### Phase 3 success gates

- Registered nodekey admitted; fresh key rejected (`derpdenytest` / `integration/derpprobe`)  
- `fail-open=false` still on ExecStart  
- TLS + STUN still pass  
- Rollback drill documented with wall-clock **measured** during this window

---

## Phase 4 — Outside-network browser forced-relay + revocation

Only after Phase 3 success (or against a lab DERP if Phase 3 deferred — but user asked to prove on real relay after cutover).

### Proofs

1. Client **outside** Sticklink LAN / Luna private net: browser + stick with `--force-relay` / ICE relay-only to `relay-tor1.stickllm.com`.  
2. Method C (or provisioned pair) → Noise → chat over DC via DERP.  
3. Revoke slot / withdraw relay permit → **new** DERP admit denied; WSS `4403` where applicable. Note Q-S6: **existing** DERP sessions may persist until reconnect.  
4. Capture: admit Allow true→false; browser/kiosk errors; no change to firewall/SSH.

### Phase 4 rollback

Same as Phase 3c (deny-all) if relay must be locked; Worker rollback separate (Phase 1).

---

## Explicit non-goals (all phases unless separately approved)

- DNS edits for `link.stickllm.com` (optional after workers.dev smoke; needs Zone DNS Edit)  
- Touching `instrumentlibrary-*`  
- Replacing derper binary / rotating `derper.key` / LE  
- Opening extra firewall ports  
- Enabling SPAKE2 (`FEATURE_SPAKE2_CODE` stays `0`)

---

## Approval signature blocks

| Phase | Approves | Interruption? | Spend |
|---|---|---|---|
| **1** CF signalling | **done** 2026-11-07 | No | Workers Paid **US$5/mo** + usage |
| **2** Stage admit `:9109` | **done** 2026-11-07 | No | $0 incremental on VPS |
| **3** derper verify cutover | **done** 2026-11-08T004513Z · 4824 ms | **Yes — derper restart** | $0 |
| **4** Outside forced-relay proof | **done** 2026-11-07 · egress 99.229.9.14 · 31/31 derp echoes · relay.del deny | No (unless rollback) | $0 |

**Not executed by this document.** Await phase-by-phase approval.
