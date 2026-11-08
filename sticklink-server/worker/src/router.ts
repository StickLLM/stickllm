// Copyright (c) 2026 Nink Inc. All rights reserved.
// Global router (singleton DO "global"): 4-digit routing IDs (PAIRING-SPEC
// §4.6) and mailbox-id -> home lookups. Holds only rid, mbx, home and times.
import { DurableObject } from "cloudflare:workers";
import { randomInt } from "./b64";
import { L, type Env } from "./config";

export class RouterDO extends DurableObject<Env> {
  private sql: SqlStorage;
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`
      CREATE TABLE IF NOT EXISTS mbx (mbx TEXT PRIMARY KEY, home TEXT NOT NULL, rid TEXT, exp INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS rid_hold (rid TEXT PRIMARY KEY, until INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS home_rid (home TEXT NOT NULL, rid TEXT NOT NULL, until INTEGER NOT NULL, PRIMARY KEY (home, rid));
      CREATE UNIQUE INDEX IF NOT EXISTS mbx_rid ON mbx(rid) WHERE rid IS NOT NULL;
    `);
  }

  private gc(now: number) {
    // Expired live mailboxes release their rid (into the 10-minute hold).
    for (const r of this.sql.exec<{ mbx: string }>("SELECT mbx FROM mbx WHERE exp<=?", now).toArray()) this.releaseAt(r.mbx, now);
    this.sql.exec("DELETE FROM rid_hold WHERE until<=?", now);
    this.sql.exec("DELETE FROM home_rid WHERE until<=?", now);
  }

  private releaseAt(mbx: string, now: number) {
    const row = this.sql.exec<{ rid: string | null }>("SELECT rid FROM mbx WHERE mbx=?", mbx).toArray()[0];
    if (!row) return;
    this.sql.exec("DELETE FROM mbx WHERE mbx=?", mbx);
    if (row.rid) this.sql.exec("INSERT OR REPLACE INTO rid_hold(rid, until) VALUES(?, ?)", row.rid, now + L.RID_RELEASE_HOLD_MS);
  }

  /**
   * Register a mailbox. For code mode also allocate a routing ID uniformly at
   * random among values that are not live, not released in the last 10 min,
   * and not used by this home in the last 24 h. Returns null rid => busy.
   */
  async open(home: string, mbx: string, expMs: number, wantRid: boolean, now = Date.now()): Promise<{ ok: boolean; rid?: string }> {
    this.gc(now);
    let rid: string | undefined;
    if (wantRid) {
      const excluded = new Set<string>();
      for (const r of this.sql.exec<{ rid: string }>("SELECT rid FROM mbx WHERE rid IS NOT NULL").toArray()) excluded.add(r.rid);
      for (const r of this.sql.exec<{ rid: string }>("SELECT rid FROM rid_hold").toArray()) excluded.add(r.rid);
      for (const r of this.sql.exec<{ rid: string }>("SELECT rid FROM home_rid WHERE home=?", home).toArray()) excluded.add(r.rid);
      if (excluded.size >= 10000) return { ok: false };
      const free = 10000 - excluded.size;
      // Pick the k-th free value, k uniform in [0, free): exactly uniform.
      let k = randomInt(free);
      for (let v = 0; v < 10000; v++) {
        const s = v.toString().padStart(4, "0");
        if (excluded.has(s)) continue;
        if (k-- === 0) {
          rid = s;
          break;
        }
      }
      this.sql.exec("INSERT OR REPLACE INTO home_rid(home, rid, until) VALUES(?, ?, ?)", home, rid!, now + L.RID_HOME_HOLD_MS);
    }
    this.sql.exec("INSERT INTO mbx(mbx, home, rid, exp) VALUES(?, ?, ?, ?)", mbx, home, rid ?? null, expMs);
    await this.arm();
    return { ok: true, rid };
  }

  async lookupRid(rid: string, now = Date.now()): Promise<{ home: string; mbx: string } | null> {
    const r = this.sql.exec<{ home: string; mbx: string }>("SELECT home, mbx FROM mbx WHERE rid=? AND exp>?", rid, now).toArray()[0];
    return r ?? null;
  }

  async lookupMbx(mbx: string, now = Date.now()): Promise<{ home: string } | null> {
    const r = this.sql.exec<{ home: string }>("SELECT home FROM mbx WHERE mbx=? AND exp>?", mbx, now).toArray()[0];
    return r ?? null;
  }

  /** Release on success, failure, cancel or expiry. Only the owning home may release. */
  async release(home: string, mbx: string, now = Date.now()): Promise<void> {
    const r = this.sql.exec<{ home: string }>("SELECT home FROM mbx WHERE mbx=?", mbx).toArray()[0];
    if (r && r.home === home) this.releaseAt(mbx, now);
  }

  async stats(now = Date.now()): Promise<{ live: number; held: number }> {
    this.gc(now);
    const live = this.sql.exec<{ n: number }>("SELECT COUNT(*) AS n FROM mbx WHERE rid IS NOT NULL").one().n;
    const held = this.sql.exec<{ n: number }>("SELECT COUNT(*) AS n FROM rid_hold").one().n;
    return { live, held };
  }

  private async arm() {
    const r = this.sql.exec<{ t: number | null }>(
      "SELECT MIN(t) AS t FROM (SELECT MIN(exp) AS t FROM mbx UNION ALL SELECT MIN(until) FROM rid_hold UNION ALL SELECT MIN(until) FROM home_rid)",
    ).one();
    if (r.t) await this.ctx.storage.setAlarm(r.t);
  }

  async alarm(): Promise<void> {
    this.gc(Date.now());
    await this.arm();
  }
}
