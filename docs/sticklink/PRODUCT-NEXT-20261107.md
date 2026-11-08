# Product next — after Phases 1–4 (2026-11-07)

## Done this pass

- Ops external health recorded: [OPS-HEALTH-20261107.md](./OPS-HEALTH-20261107.md)
- Shipping endpoints file: `overlay/etc/sticklink/sticklinkd.json` (`wss://link.stickllm.com`, DERP `relay-tor1`, pinned `prod-1`)
- `sticklinkd run` auto-loads that path when present on the stick
- Legacy LAN `stickllm-pair` **kept**; SPAKE2 stays off

## Method C (enrolment) — remaining

| Step | Status |
|---|---|
| Lab Method C vs local wrangler | Done (E2E + negatives) |
| Force-relay chat vs live DERP | Done (Phase 4; file-pair, not QR UI) |
| Method C QR vs **live** `link.stickllm.com` | **PASS** full browser E2E — [E2E-METHOD-C-LIVE-20261107.md](./E2E-METHOD-C-LIVE-20261107.md) |
| Native VT approval overlay | **Next / blocked for shipping** — lab must not ship `pair_qr_lab` / bypass |
| Wire kiosk / UI to show Method C QR | **Next** |
| Make Method C default; retire LAN pair | Only after HW validation |

## Sticklinkd on a real stick (when you want ISO/hotfix)

1. Provision device (`ak` → D1) like lab stick.
2. Ensure overlay has `/etc/sticklink/sticklinkd.json` (pinned keys — avoids CF UA 1010 on `/v1/keys`).
3. Registry unlock story still test-shim (`STICKLINK_TESTING` + `--registry-key-file`) until combined PIN+key-file lands.
4. Hotfix overlay bits; do **not** flash a shipping tag over an existing name.

## Sticklink operator

Run the on-relay checklist in OPS-HEALTH and paste results. No config change unless a unit is unhealthy.
