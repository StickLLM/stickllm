// Copyright (c) 2026 Nink Inc. All rights reserved.
// Limits from SIGNALLING-PLAN §2.4 and PAIRING-SPEC v0.9 §5/§6 (spec wins).

export const SUBPROTOCOL = "sticklink.1";

export const L = {
  FRAME_MAX: 4096,
  BURST: 20,
  RATE_PER_S: 1,
  SLOTS_MAX: 16,
  CLIENTS_MAX: 8,
  UNAUTH_MS: 10_000,
  MBX_JOIN_MS: 5_000,
  JOIN_FAIL_MAX: 5,
  JOIN_LOCK_MS: 15 * 60_000,
  UPGRADES_PER_MIN: 30,
  MBX_CONN_PER_MIN: 10,
  LOOKUP_FAIL_PER_H: 100,
  LOOKUP_BLOCK_MS: 60 * 60_000,
  PAIR_PER_10MIN: 5,
  PAIR_PER_DAY: 20,
  PAIR_LOCK_MS: 60 * 60_000,
  MBX_EXP_S: 60,
  MBX_CONNS: 4,
  RID_RELEASE_HOLD_MS: 10 * 60_000,
  RID_HOME_HOLD_MS: 24 * 60 * 60_000,
  SLOT_PENDING_MAX_S: 600,
  PERMIT_TTL_S: 12 * 3600,
  PERMITS_PER_HOLDER: 2,
  RELAY_REG_PER_DAY: 10,
  ALLOWLIST_TTL_S: 15 * 60,
  REVOKED_PAGE: 64,
  BOX_MAX: 3072,
  AUDIT_PAGE: 100,
  AUDIT_KEEP_S: 365 * 86400, // Q-S23: audit rows kept 1 year, then pruned by the cron
} as const;

export interface RelayInfo {
  rg: string;
  host: string;
  stun: number;
}

export interface Env {
  HOME: DurableObjectNamespace<import("./home").HomeDO>;
  ROUTER: DurableObjectNamespace<import("./router").RouterDO>;
  LIMITER: DurableObjectNamespace<import("./limiter").LimiterDO>;
  FEED: DurableObjectNamespace<import("./feed").FeedDO>;
  DB: D1Database;
  // secrets
  IP_PEPPER: string;
  SIGNING_KEY: string; // Ed25519 32 B seed base64url
  SIGNING_KID: string;
  RELAY_TOKENS: string; // JSON {"tor1":"<sha256 hex of bearer token>"}
  // vars
  RELAYS: string; // JSON RelayInfo[]
  FEATURE_SPAKE2_CODE: string; // "1" enables pair.open m:"code" (default "0", §8b(a))
  MBX_GRACE_S?: string; // extra seconds an in-progress pairing may run past exp (default 0)
  TEST_RELAY_REG_PER_DAY?: string; // local E2E only: honoured only with a "test-" SIGNING_KID (Q-S21)
}

/** relay.reg daily quota per holder. The override exists for repeated local E2E runs and is
 *  ignored unless the signing key is a test key, so a stray var cannot loosen production. */
export function relayRegPerDay(env: Env): number {
  const o = Number(env.TEST_RELAY_REG_PER_DAY);
  if (env.TEST_RELAY_REG_PER_DAY && env.SIGNING_KID?.startsWith("test-") && Number.isInteger(o) && o > 0) return o;
  return L.RELAY_REG_PER_DAY;
}

export function relays(env: Env): RelayInfo[] {
  try {
    return JSON.parse(env.RELAYS) as RelayInfo[];
  } catch {
    return [];
  }
}

export const codeModeEnabled = (env: Env) => env.FEATURE_SPAKE2_CODE === "1";
