# Lab bypass of trusted local approval (explicit)

The browser ↔ aiortc harness is **not** the shipping approval path.

| Shipping (PAIRING-SPEC §4.7) | This lab harness |
|---|---|
| Native VT / `sticklink-approve` overlay; user types/taps a fresh 4-digit Allow | **Bypassed** — never shown |
| Optional lab gate: `LabPairSession.approve_local(token)` on a trusted local kiosk | **Bypassed** — `kiosk_stick.py` opens the mailbox and continues without `approve_local` |
| Record saved only after pair-confirm | Lab still runs pair_psk + pair-confirm over the DC for crypto proof |

Flags required for any Method C lab code: `STICKLINK_TESTING=1` and `STICKLINK_LAB=1`.
Do not enable `pair_qr_lab` or this harness on shipping images.

Reports must set `lab_bypass_trusted_approval: true` when this path was used.
