# StickLLM v0.7.0 — StickLink cutover ship

First ISO line that includes StickLink overlay + production endpoint wiring after live Phases 1–4.

## In this ship

- `sticklinkd` + `overlay/usr/local/lib/sticklink/` (Noise, DERP, Method C schedule)
- Shipping config `overlay/etc/sticklink/sticklinkd.json` → `wss://link.stickllm.com`, DERP `relay-tor1`, pinned `prod-1`
- Legacy LAN `stickllm-pair` **kept** (Method C not yet default enrolment UI)
- Lab harnesses under `sticklink-server/lab-browser-e2e/` (including live E2E against link)
- Docs under `docs/sticklink/` (deploy phases, ops health, Method C live report)

## Proven before bake

- Phases 1–4 on live CF + `relay-tor1` (admit cutover, force-relay chat, relay.del deny)
- On-relay ops confirm (Sticklink)
- Live Method C browser E2E vs `link.stickllm.com` (lab bypass — not shipping VT)

## Not in this ship / still open

- Native VT approval overlay (lab bypass must not ship as default UX)
- Kiosk Method C QR as default replacing LAN pair
- Combined registry unlock (still `STICKLINK_TESTING` shim for registry-key-file)
- SPAKE2 (`FEATURE_SPAKE2_CODE=0`)

## Artifacts

- Tag: `v0.7.0`
- ISO: `out/v0.7.0/StickLLM-v0.7.0.iso`
- Checksum: `checksums/v0.7.0.sha256`

Do not overwrite prior shipping tags or ISO names.
