<!-- Copyright (c) 2026 Nink Inc. All rights reserved. -->
# Signalling vectors (TEST ONLY)

| File | Generator | Checked by |
|---|---|---|
| `signalling-v2.json` | `gen_signalling_vectors.py ../../vectors/kvm-usb-v1.json ../../vectors/qr-v1.json signalling-v2.json` | `worker/test/unit/vectors.test.ts`, `sidecar/internal/admit/admit_test.go`, `slpeer -selftest` |
| `ikpsk2-v2.json` | `gen_ikpsk2_vectors.py signalling-v2.json` (needs `noiseprotocol==0.3.1` and `cryptography`) | `worker/test/worker/session.test.ts` (sig frame), `slpeer -selftest`; device teams for Noise |

Both are deterministic: running a generator again gives identical bytes.

v2 (2026-10-29, Nink's decisions on OPEN-QUESTIONS Q-N1 and Q-S1) replaces v1; the v1 files are removed:

* `signalling-v2.json` `device`: the hello is an **Ed25519 signature** by the device's own
  server-auth key (`'sl1/dev-hello/v1' || 0x00 || n || dev || role || home`), plus an
  `auth.rotate` proof-of-possession vector. The v1 HMAC `dev_secret`/`DEV_MASTER` vectors are gone.
  All other sections (slot_join, qr_join, signing, permit, allowlist, revoked) are byte-identical to v1.
* `ikpsk2-v2.json`: the network prologue is 96 bytes,
  `'sl1/net' || ver(0x01) || home(16) || slot(8) || initiator_static_pub(32) || responder_static_pub(32)`;
  msg1/msg2/handshake hash/transport values change accordingly. `prologue_mismatch_responder_rejects_msg1`
  records that swapped statics, another slot, ver 2 and the old 31-byte v1 prologue all fail at msg1.
