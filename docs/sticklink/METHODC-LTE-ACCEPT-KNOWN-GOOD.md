# Method C LTE acceptance — known-good preserve

**Status:** iPhone LTE real-world acceptance passed (operator, 2026-11-08).  
**Frozen join build id:** `methodc-lte-accept-20261108.1`  
**Git tag:** `methodc-lte-accept-20261108.1`  
**Branch at preserve:** `feature/sticklink-browser-lab`

| Field | Value |
|-------|--------|
| Commit | `860ea3ccd6ed1b5bee6c587317eba1435420f646` |
| Tag | `methodc-lte-accept-20261108.1` |
| Prior tip (pre-preserve) | `412113d` (`Ship StickLink phone QR under Devices & Pairing for v0.7.2.`) |

## What this preserve covers

Working Method C path only (no alternate connection methods):

- Rendezvous: `wss://link.stickllm.com/v1/ws`, `pair.open` → `sl1:` QR
- WebRTC + Noise. Lab acceptance ICE was **direct**; do not claim TURN/DERP browser fallback without a recorded relay ICE type
- App-mux HTTP tunnel: gzip (`x-sticklink-ce`), concurrency `HTTP_MAX` / `Semaphore(8)`
- Service worker static cache `sticklink-a0-static-v1`; authenticated API responses not cached
- Cloudflare join page only; Agent Zero **not** proxied over bootstrap HTTP (`a0_via_sticklink_dc_only`)
- Stick Devices & Pairing QR publish (`stickllm-sticklink-join-publish` + gateway remint API)
- Lab: `run_phone_join_lab.py`, `kiosk_agent_session.py`, `app_mux_bridge.py`, join/SW/mux/perf assets

## Rollback

Return the tree to this exact known-good (detached or new branch):

```text
git fetch github tag methodc-lte-accept-20261108.1
git switch --detach methodc-lte-accept-20261108.1
# or: git switch -c restore/methodc-lte-accept methodc-lte-accept-20261108.1
```

Verify:

```text
git rev-parse HEAD
git rev-parse methodc-lte-accept-20261108.1
# both must equal 860ea3ccd6ed1b5bee6c587317eba1435420f646
rg -n "methodc-lte-accept-20261108.1" sticklink-server/lab-browser-e2e/browser/agent_join.html
```

Lab-only file snapshot (pre-optimize baseline copies):  
`sticklink-server/lab-browser-e2e/_rollback_baseline_20261108/`

Do **not** retag or force-move `methodc-lte-accept-20261108.1` after it is pushed.  
Do **not** overwrite shipping tags (`v0.7.0`, future `v0.7.2`, …) with this preserve.

## Release ISO note

This tag freezes source **before** the release ISO bake. Shipping ISO tag/checksum (`v0.7.2` / `checksums/v0.7.2.sha256`) are separate and must only be cut after a clean bake of this known-good (or a deliberate descendant).
