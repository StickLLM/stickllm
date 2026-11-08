-- Copyright (c) 2026 Nink Inc. All rights reserved.
-- Directory (D1). No IPs, no device secrets, no pairing material is stored here.

-- Devices (sticks, AI KVMs). Server-auth is a per-device Ed25519 public key
-- `ak`, added in 0002_dev_auth_audit.sql (the DEV_MASTER scheme was removed).
CREATE TABLE devices (
  dev TEXT PRIMARY KEY,            -- 16 B base64url
  kind TEXT NOT NULL CHECK (kind IN ('stick', 'kvm')),
  gen INTEGER NOT NULL DEFAULT 0,  -- credential generation (rotation)
  home TEXT,                       -- sticks only: issued at provisioning
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
  cls TEXT NOT NULL DEFAULT 'none', -- relay entitlement class: none|stick|kvm|sub
  ent_until INTEGER NOT NULL DEFAULT 0, -- unix s; relay entitlement expiry
  created INTEGER NOT NULL
);
CREATE UNIQUE INDEX devices_home ON devices(home) WHERE home IS NOT NULL;

CREATE TABLE homes (
  home TEXT PRIMARY KEY,           -- 16 B base64url
  owner TEXT NOT NULL REFERENCES devices(dev),
  created INTEGER NOT NULL
);

-- Live relay permits. One row per node key.
CREATE TABLE permits (
  nk TEXT PRIMARY KEY,             -- nodekey:<64 hex>
  rg TEXT NOT NULL,
  e INTEGER NOT NULL,              -- unix s expiry
  home TEXT NOT NULL,
  slot TEXT,                       -- set when issued to a slot-joined client
  holder TEXT NOT NULL,            -- dev id, or home/slot for credential-less clients
  cls TEXT NOT NULL,
  iat INTEGER NOT NULL
);
CREATE INDEX permits_rg ON permits(rg, e);
CREATE INDEX permits_holder ON permits(holder, iat);
CREATE INDEX permits_slot ON permits(home, slot);

-- Append-only change log feeding allowlist deltas. seq is the allowlist seq.
CREATE TABLE al_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  rg TEXT NOT NULL,
  op TEXT NOT NULL CHECK (op IN ('add', 'del')),
  nk TEXT NOT NULL,
  ts INTEGER NOT NULL
);
CREATE INDEX al_log_rg ON al_log(rg, seq);

-- relay.reg daily counter per holder.
CREATE TABLE reg_rate (
  holder TEXT NOT NULL,
  day INTEGER NOT NULL,
  n INTEGER NOT NULL,
  PRIMARY KEY (holder, day)
);
