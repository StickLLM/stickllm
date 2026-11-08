# StickLLM v0.7.2 — StickLink phone QR under Pairing

## In this ship

- **Devices & Pairing** shows the **StickLink join QR** (cellular / remote Agent Zero) — the same join URL the phone lab publishes, not the LAN address
- Gateway `GET /api/pair/sticklink-join` (kiosk) reads `/run/stickllm/sticklink-join.json`
- Lab `run_phone_join_lab.py` publishes that file when the public join URL is ready
- Vendored `ui/vendor/qrcode/`; `stickllm-hotfix` installs `ui/vendor/`
- SearXNG preferred engines (Bing / Yahoo / Seznam / Wikipedia) for shared-egress CAPTCHA

## Known issues (fix later — do not block this bake)

- **LAN / desktop Agent Zero via original pairing is broken** after StickLink phone-join lab work. Phone StickLink QR works; restoring desktop LAN Agent Zero pairing is a follow-up.

## Not in this ship

- Method C `sl1:` QR as default enrolment (still needs native VT approval)
- Retiring LAN pair code (kept as secondary card)
- Fix for LAN/desktop Agent Zero pairing (above)

## Artifacts

- Tag: `v0.7.2` (after HW confirm)
- ISO: `out/v0.7.2/StickLLM-v0.7.2.iso`
- Checksum: `checksums/v0.7.2.sha256`
