-- Copyright (c) 2026 Nink Inc. All rights reserved.
-- Nink, 2026-10-29 (OPEN-QUESTIONS Q-S1, Q-S12):
--  * Device server-auth: each device generates its own random Ed25519 keypair on the
--    device; only the public key `ak` is stored here (a verifier, not a secret). The old
--    DEV_MASTER derivation is removed. `gen` now counts auth-key rotations.
--  * Audit log of device/slot management operations: who, what, target, when, result.
--    Never holds keys, MACs, jk, PSKs, nonces or IPs.
ALTER TABLE devices ADD COLUMN ak TEXT;  -- 32 B Ed25519 public key, base64url; NULL = cannot authenticate
CREATE UNIQUE INDEX devices_ak ON devices(ak) WHERE ak IS NOT NULL;

CREATE TABLE audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,                 -- unix s
  home TEXT NOT NULL,                  -- home the operation applies to ('-' for ops rows with no home)
  actor_kind TEXT NOT NULL CHECK (actor_kind IN ('stick', 'admin', 'device', 'system', 'ops')),
  actor TEXT NOT NULL,                 -- stick dev id | admin slot id | device dev id | 'expiry' | operator label
  op TEXT NOT NULL,                    -- slot.add | slot.del | slot.rekey | slot.expire | auth.rotate | dev.disable | dev.enable | dev.setak
  target TEXT,                         -- slot id or dev id (public ids only)
  result TEXT NOT NULL                 -- ok | auth | nf | busy | bad
);
CREATE INDEX audit_home ON audit(home, seq);
