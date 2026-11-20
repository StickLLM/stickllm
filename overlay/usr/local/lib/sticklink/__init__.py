"""sticklink stick-side key storage (PAIRING-SPEC v0.9 §0 P1, §3, §6).

Modules:
  fsio     atomic writes, temp cleanup, the sticklink/.lock flock
  crypto   HKDF, ChaCha20-Poly1305, Argon2id (libsodium), X25519
  formats  pinned sealed-file byte formats (§3 table)
  phrase   recovery phrase / PIN rules and word lists
  luks     the pinned cryptsetup keyslot procedure
  registry registry_key, identity.sealed, records/
  unlock   combined unlock secret, setup, migration, R5, PIN/phrase change
  revoked  remove-only revoked-peer pull over the signalling WebSocket
"""

SETTINGS_MNT = "/mnt/stickllm-settings"
SL_DIRNAME = "sticklink"
