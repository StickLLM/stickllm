# Browser ↔ aiortc Method C E2E (local wrangler) — 2026-11-07

## Result: **PASS**

Harness: `sticklink-server/lab-browser-e2e/run_e2e.py`  
Stack: local `wrangler dev --local` only (port 8800 this run).  
**No** Cloudflare resource creation, Paid activation, DNS changes, or relay changes.

| Proof | Status |
|---|---|
| Method C QR mailbox join (`pair.open` / `pair.join` + join MAC) | PASS |
| WebRTC DataChannel (aiortc kiosk ↔ Chromium) | PASS |
| Pinned Noise IKpsk2 over DC (`boot_psk` from Method C TH; initiator static pinned) | PASS (`hh` matched both sides) |
| Chat streaming + mid-stream cancel | PASS (3 chunks then `chat_cancel` / `chat_cancelled`) |
| Revocation (`slot.add` then `slot.del`; browser saw `revoked_ok`) | PASS |

Artifact: `sticklink-server/lab-browser-e2e/state/results/e2e-report.json`

```json
"proven": {
  "method_c_mailbox": true,
  "noise_pinned_dc": true,
  "chat_stream_cancel": true,
  "revocation_slot_del": true
}
```

Noise handshake hash (both sides): `ad3df25b4e3d07f54f90a218c105f8eaa02b470dff012ceaff1e86c01a3e834c`

## Recurring cost (**estimates only** — not billing-confirmed)

| Item | Estimate |
|---|---|
| Cloudflare Workers Paid | ~US$5/mo (currency, plan tier, and included usage limits **unverified** until dashboard/billing confirm) |
| Luna Node `relay-tor1` | ~US$3.50/mo (existing; confirm currency on invoice) |
| **New spend at first CF deploy** | **estimate ≈ US$5/mo** — not activated |

Do not treat these figures as confirmed recurring cost until plan, currency, and usage limits are read from the live billing UI.

## Secrets required at deploy (names only)

Set via `wrangler secret put` (values from offline `gen-prod-secrets.mjs`; never chat/repo):

| Secret name | Purpose |
|---|---|
| `IP_PEPPER` | IP rate-limit hashing |
| `SIGNING_KEY` | Ed25519 seed for permits / allowlist / revoked envelopes |
| `RELAY_TOKENS` | JSON map `rg → sha256(token)` for admit sidecar |

Vars (not secrets): `SIGNING_KID`, `RELAYS`, `FEATURE_SPAKE2_CODE=0`, `MBX_GRACE_S`.

Placeholder D1 `database_id` remains until deploy-approval `wrangler d1 create sticklink`.

## Relay admission (read-only) — **not verified this session**

`%USERPROFILE%\.ssh\sticklink_relay` is **absent** on this PC. Recorded key home is
Sticklink’s assistant computer `~/.ssh/sticklink_relay` — not assumed to be the
LAN box. No host search / no replacement key. Checklist prepared at
`RELAY-INVENTORY-CHECKLIST.md`. Keep deny-all until separately approved cutover.

## Lab bypass (explicit)

This E2E sets `lab_bypass_trusted_approval: true`. See
`sticklink-server/lab-browser-e2e/LAB-BYPASS.md`: native VT overlay and
`LabPairSession.approve_local` are skipped.

## Gaps still open

- Live relay admit inventory + measured rollback (key transfer pending)
- `workers.dev` / Workers Paid / remote D1 — **deployment + spending pending**
- Unrelated account resources (`instrumentlibrary-*`) left untouched
