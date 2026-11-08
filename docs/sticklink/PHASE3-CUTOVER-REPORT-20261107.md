# Phase 3 report — 2026-11-07

**COMPLETE.** Production admit cutover on `relay-tor1`. Derper verifies against `sticklink-admit` on `:9099`.

## Sticklink paste-back

| Check | Result |
|---|---|
| Status | **PHASE3_CUTOVER_OK** |
| Backup | `/root/sticklink-relay-bak-20261108T004513Z` |
| `derper` restart wall | **4824 ms** |
| `sticklink-admit` | **active/enabled** on `127.0.0.1:9099` |
| `derper` | **active/enabled**, restarted |
| `derp-admit` | **inactive/disabled** |
| `sticklink-admit-stage` | **inactive/disabled**; `:9109` closed |
| `:9099 /healthz` | HTTP **200** |
| Unknown nodekey POST | `Allow:false` |
| `DERP_VERIFY_URL` | **unchanged** (`http://127.0.0.1:9099/derp/admit`) |
| fail-open | **false** |

## What changed

- Real admit (`sticklink-admit`) owns production verify port `:9099`
- Stage unit and `:9109` removed from service
- Legacy `derp-admit` (deny-all) stopped/disabled
- Derper unit dependency retargeted to `sticklink-admit.service`; derper restarted once (~4.8 s)

## Unchanged

- Identity / certs / nftables / SSH / public ports
- `DERP_VERIFY_URL` path and fail-open=false
- Signalling (`https://link.stickllm.com`) and D1

## Rollback (if needed)

```bash
sudo ./rollback.sh /root/sticklink-relay-bak-20261108T004513Z
```

(Package remains on operator PC: `C:\Users\peter\stickllm\_sticklink-phase3-cutover-20261107\`.)

## Follow-on

Phase 4 complete — see [PHASE4-OUTSIDE-REPORT-20261107.md](./PHASE4-OUTSIDE-REPORT-20261107.md).
