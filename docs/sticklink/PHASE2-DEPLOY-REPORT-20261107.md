# Phase 2 report — 2026-11-07

**COMPLETE.** Staging admit live on relay `:9109`. Derper / `derp-admit` / `:9099` deny-all **unchanged**.

## Relay install confirmation (Sticklink)

| Check | Result |
|---|---|
| `sticklink-admit-stage` | **active, enabled** |
| `derper` | **active**, not restarted |
| `derp-admit` | **active** |
| `:9109 /healthz` | HTTP **200** `ok` |
| POST unknown nodekey `:9109` | `Allow:false` |
| POST same unknown `:9099` | `Allow:false` |
| `DERP_VERIFY_URL` | `http://127.0.0.1:9099/derp/admit` |
| Listeners | `127.0.0.1:9099` and `127.0.0.1:9109` |
| Binary SHA256 | matches `62D964776880FFAB736C505D627B3C29C5D6D65FADF51E51AD6BA3130DCE25FE` |
| Production config / firewall / PIDs·start times | **unchanged** |

## Crypto / feed proof (this PC, loopback `:9109`)

Ran `sticklink-admit` locally with `-base https://link.stickllm.com` (same binary flags as stage unit):

| Check | Result |
|---|---|
| Signed allowlist pull + `/healthz` | **200** `ok` |
| Unknown `nodekey` POST `/derp/admit` | `{"Allow":false}` |
| GET `/derp/admit` probe | `{"Allow":false}` |
| After lab stick `relay.reg` | `{"Allow":true}` |
| After `relay.del` | `{"Allow":false}` |
| State file | `allowlist-tor1.json` persisted |

Local process stopped after proof. **Not** left running.

## Artifact for Sticklink relay install

Directory: `E:\sticklink-phase2\` (also secrets copies — treat as sensitive)

| File | Notes |
|---|---|
| `sticklink-admit` | linux/amd64, sha256 `62D964776880FFAB736C505D627B3C29C5D6D65FADF51E51AD6BA3130DCE25FE` |
| `sticklink-admit-stage.service` | listen `127.0.0.1:9109`, base `https://link.stickllm.com` |
| `admit-token` / `admit-keys` | from Phase 1 secrets (0600/644 on relay) |
| `install-stage.sh` | idempotent stage install + verify; **does not** touch derper |

### Sticklink: apply on `relay-tor1` (when ready)

```bash
# from machine that has sticklink_relay SSH
scp -i ~/.ssh/sticklink_relay -r E:/sticklink-phase2/* debian@relay-tor1.stickllm.com:/tmp/sticklink-phase2/
ssh -i ~/.ssh/sticklink_relay debian@relay-tor1.stickllm.com 'chmod +x /tmp/sticklink-phase2/install-stage.sh && /tmp/sticklink-phase2/install-stage.sh'
```

Expect: `sticklink-admit-stage` active; `:9109` healthz ok; unknown deny; **`derp-admit` still active on `:9099`**; `DERP_VERIFY_URL=http://127.0.0.1:9099/derp/admit`.

## Not done (Phase 3+ — separate approval)

- No derper restart / verify URL change  
- No outside forced-relay (Phase 4)