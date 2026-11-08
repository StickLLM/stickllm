# Proposed deployment + rollback (for approval — not executed)

**Superseded for execution detail by**  
[`DEPLOY-APPROVAL-PLAN-20261107.md`](DEPLOY-APPROVAL-PLAN-20261107.md)  
Live relay facts: [`RELAY-INVENTORY-20261107-LIVE.md`](RELAY-INVENTORY-20261107-LIVE.md)  
(Sticklink inventory 2026-11-07 18:28–18:29 EST).

Preconditions from `CF-INVENTORY-20261107.md`: account
`83ead3dd06c02e0011d009fb1cc13e5f`, zone `stickllm.com` /
`306f7ad2934d6b221ed3818116ac845d`. No StickLink Worker/D1/DO exists yet.

## Order

1. **CF signalling** deploy + smoke — leave `derp-admit` deny-all on `127.0.0.1:9099`.
2. **Stage** `sticklink-admit` on `127.0.0.1:9109`; prove feed / expiry / revoke / fail-closed.
3. **Back up** live unit files + `/etc/default/derper`; switch derper verify to real sidecar — **requires `systemctl restart derper` and interruption approval**.
4. **Outside-network** browser forced-relay + revocation proof.

## Confirmed list-price cost (USD, CF docs 2026-11-07)

- Workers Paid minimum **US$5.00/mo** (10M Worker req, DO 1M req + 400k GB-s includes, etc.).
- Luna Node relay ~US$3.50/mo existing (confirm invoice currency).
- Account billing still to confirm Paid is active before Phase 1 runs.

## Conditional relay rollback (inventory)

Restore `DERP_VERIFY_URL=http://127.0.0.1:9099/derp/admit`, enable `derp-admit.service`, restore derper `Wants=`/`After=`, `systemctl restart derper`. Preserve `derper.key`, certs, nftables, SSH.

## Explicit non-goals until separate approval

DNS for `link.stickllm.com`, SPAKE2, unrelated CF resources, derper binary/key rotation.
