# Browser ↔ aiortc Method C — pair_psk / negatives / relay prep — 2026-11-07b

## Result: **PASS** (local wrangler only)

No Cloudflare create/Paid/DNS. No relay changes. Admission stays deny-all until a
separately approved cutover. Deployment and spending remain **pending**.

### Positive path (`lab-browser-e2e/run_e2e.py`)

| Proof | Status |
|---|---|
| Method C mailbox join | PASS |
| Pinned Noise IKpsk2 over DataChannel | PASS |
| `pair_psk` contributions + pair-confirm (i/r) | PASS (fps matched both sides) |
| Chat stream + cancel | PASS |
| `slot.add` → `slot.del` | PASS |

Artifact: `sticklink-server/lab-browser-e2e/state/results/e2e-report.json`  
`lab_bypass_trusted_approval: true` (see `lab-browser-e2e/LAB-BYPASS.md`).

### Negative path (`lab-browser-e2e/run_negatives.py`)

| Case | Expected | Status |
|---|---|---|
| wrong_pin (mutated QR `K`) | Noise fails | PASS |
| wrong_psk (kiosk random `boot_psk`) | Browser rejects msg2 (invalid tag) | PASS |
| tamper (corrupted AEAD after confirm) | Browser decrypt fails | PASS |
| revoked_reconnect (join after `slot.del`) | `err{code:auth}` | PASS |

Artifact: `sticklink-server/lab-browser-e2e/state/results/negatives-report.json`

Unit: `tests/sticklink/test_pair_psk_confirm.py` — 3 passed (plus existing `test_pair_qr`).

## Lab bypass of trusted local approval (explicit)

Shipping needs native VT / `sticklink-approve` (PAIRING-SPEC §4.7). This harness:

1. Never shows the native overlay.
2. Never calls `LabPairSession.approve_local` — kiosk opens the mailbox and continues.

Documented in `sticklink-server/lab-browser-e2e/LAB-BYPASS.md`. Not for shipping images.

## Recurring cost (**estimates only**)

| Item | Estimate | Status |
|---|---|---|
| Cloudflare Workers Paid | ~US$5/mo | **Unconfirmed** — currency, plan tier, included request/DO/D1 limits need dashboard/billing read |
| Luna Node `relay-tor1` | ~US$3.50/mo | Existing; confirm currency on invoice |
| New spend if CF deploy approved later | estimate ≈ US$5/mo | **Not activated** |

## Secrets at deploy (names only — values offline)

`IP_PEPPER`, `SIGNING_KEY`, `RELAY_TOKENS`. Vars: `SIGNING_KID`, `RELAYS`, `FEATURE_SPAKE2_CODE=0`, `MBX_GRACE_S`.

## Relay inventory — prepared, not executed

- Key recorded on **Sticklink’s assistant computer** at `~/.ssh/sticklink_relay` (not assumed to be the LAN box).
- On this agent PC: key **ABSENT**. No host search. No replacement key. Transfer not claimed.
- Checklist: `docs/sticklink/RELAY-INVENTORY-CHECKLIST.md`
- **Actual** live unit names, admit binary, and rollback procedure: **unknown until SSH**. Do not approve cutover from docs-only names (`derp-admit` / ~1 min) alone.
- Keep deny-all until separately approved cutover.

## Not requesting yet

Deployment approval, Workers Paid spend, D1 create, DNS edits, relay admit cutover.
Report actual relay configuration + rollback from inventory **before** any deploy approval request.
