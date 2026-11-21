# StickLink first-boot provision (lab)

## Why 0.7.7 Generate failed once

v0.7.7 baked `stickllm-methodc-peer` with `SL_JOIN_PUBLIC_BASE=https://link.stickllm.com`, but **never** created `/var/lib/sticklink` device identity or registered the Ed25519 public key (`ak`) in D1. The peer’s WSS `hello` then 404’d (unknown device). Remint spam was a symptom, not the root cause.

A later local-only `bootstrap-ids` hotfix that minted random `dev`/`home` **without** cloud register reproduced the same 404. Do not use that path.

If `pair.open` returns `code:rate` with `retry`, the peer must sleep that many seconds **without** treating `remint.req` as an interrupt, and must **clear** any queued `remint.req` so a leftover Generate/lab remint cannot fire the instant the lock lifts. A parser that only handled HTTP 429 (or kept reminting during the 5s session backoff) caused a remint hammer and a ~10 minute home lock. Phone scan/join must never write `remint.req` — only Devices & Pairing Generate / Refresh.

## Correct path

1. Stick generates Ed25519 auth seed locally (never leaves the stick).
2. Stick POSTs only `ak` to `https://link.stickllm.com/v1/lab/device-provision` with Bearer `STICKLINK_LAB_PROVISION_TOKEN`.
3. Worker inserts `devices` + `homes` and returns `{dev,home,ak}`.
4. Stick writes `device.ids.json` + `device-auth-seed` under `/var/lib/sticklink`.
5. `stickllm-methodc-peer` starts and can `pair.open`.

## Bake

On the build host before live-build / chroot hook `0110-methodc-venv`:

```bash
export STICKLINK_LAB_PROVISION_TOKEN="$(tr -d '\r\n' < /path/to/lab-provision-token)"
# optional override:
# export STICKLINK_LAB_PROVISION_URL=https://link.stickllm.com/v1/lab/device-provision
```

The hook writes `/etc/stickllm/sticklink-factory.env` (mode 600) and enables `stickllm-sticklink-ensure-identity.service`, which runs **Before** `stickllm-methodc-peer.service`.

Do not commit the token. Lab secret file on the operator PC: `sticklink-secrets/lab-provision-token`. Worker secret name: `LAB_PROVISION_TOKEN`.
