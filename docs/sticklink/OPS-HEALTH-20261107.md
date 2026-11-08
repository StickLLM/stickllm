# StickLink ops health — 2026-11-07 (post Phase 4)

External checks from Peter’s PC. On-box relay checks need Sticklink SSH (`~/.ssh/sticklink_relay`).

## External (this host)

| Probe | Result |
|---|---|
| `https://link.stickllm.com/healthz` | **200** `ok` (curl; Python urllib may see CF **1010**) |
| Method C `pair.open`/`pair.close` (lab stick WSS) | **PASS** 2026-11-07 |
| `https://link.stickllm.com/v1/keys` | **200** kid=`prod-1` |
| `https://sticklink-signalling.stickllm.workers.dev/healthz` | **200** `ok` |
| Allowlist unauthenticated | **401** (expected) |
| `https://relay-tor1.stickllm.com/` | **200** |
| `GET /derp` without Upgrade | **426** Upgrade Required (derper up) |

**Note:** Cloudflare may return **403 / error 1010** to bare Python `urllib` User-Agents. Prefer curl, or pin `sign_keys` in `sticklinkd.json` (shipping path) so sticks never depend on live `/v1/keys` fetch.

## Phase 3 backup (relay)

`/root/sticklink-relay-bak-20261108T004513Z` — rollback via Phase 3 `rollback.sh` if admit must be reverted.

## On-relay confirm (Sticklink paste-back)

| Check | Result |
|---|---|
| `sticklink-admit` | **active** |
| `derper` | **active** |
| `derp-admit` | **inactive** |
| `sticklink-admit-stage` | **inactive** |
| `:9099` | loopback-only, `sticklink-admit` |
| `:443` | listening, derper |
| `:9109` | **no listener** |
| `DERP_VERIFY_URL` | `http://127.0.0.1:9099/derp/admit` |
| `/healthz` | **ok** |
| Unknown nodekey | `{"Allow":false}` |
| Phase 3 backup | **exists**, root-only permissions |

**Verdict:** production admit cutover still healthy; deny-all and stage remain off.

Follow-on: live Method C browser E2E **PASS** — [E2E-METHOD-C-LIVE-20261107.md](./E2E-METHOD-C-LIVE-20261107.md).


## Sticklink: on-relay checklist (paste)

```bash
ssh -i ~/.ssh/sticklink_relay -o IdentitiesOnly=yes debian@relay-tor1.stickllm.com '
set -e
echo "=== units ==="
systemctl is-active sticklink-admit derper
systemctl is-enabled sticklink-admit derper
systemctl is-active derp-admit sticklink-admit-stage 2>/dev/null || true
echo "=== listeners ==="
ss -lntp | grep -E ":443|:9099|:9109|:3478" || true
echo "=== verify url / fail-open ==="
grep -E "DERP_VERIFY|FAIL" /etc/default/derper || true
echo "=== admit healthz + unknown deny ==="
curl -fsS http://127.0.0.1:9099/healthz; echo
curl -fsS -X POST http://127.0.0.1:9099/derp/admit \
  -H "Content-Type: application/json" \
  -d "{\"NodePublic\":\"nodekey:$(openssl rand -hex 32)\"}"; echo
echo "=== backup still present ==="
ls -ld /root/sticklink-relay-bak-20261108T004513Z
'
```

Expect: `sticklink-admit` + `derper` active/enabled; `derp-admit` / stage inactive; `:9099` healthz ok; unknown `Allow:false`; `DERP_VERIFY_URL=http://127.0.0.1:9099/derp/admit`; backup dir present.

Paste back the checklist output (no secrets).

## No changes this check

Did not restart derper, rotate keys, edit DNS, or touch CF resources.
