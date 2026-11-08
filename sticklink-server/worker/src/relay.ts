// Copyright (c) 2026 Nink Inc. All rights reserved.
// Relay permits and the signed allowlist served to sticklink-admit.
import { b64u, utf8 } from "./b64";
import { L, type Env, relays, relayRegPerDay } from "./config";
import { DOM_ALLOWLIST, DOM_PERMIT, getSigner, signEnvelope } from "./crypto";
import { nowS } from "./proto";

export const signer = (env: Env) => getSigner(env.SIGNING_KEY, env.SIGNING_KID);

export interface Holder {
  home: string;
  slot: string | null;
  holder: string;
  cls: string;
}

export type RegResult = { ok: true; exp: number; tok: string; seq: number } | { ok: false; code: "rate" | "auth" | "bad" };

export async function registerPermit(env: Env, h: Holder, nk: string, rg: string): Promise<RegResult> {
  if (!relays(env).some((r) => r.rg === rg)) return { ok: false, code: "bad" };
  const db = env.DB;
  const now = nowS();
  const day = Math.floor(now / 86400);
  const cnt = await db
    .prepare("INSERT INTO reg_rate(holder,day,n) VALUES(?1,?2,1) ON CONFLICT(holder,day) DO UPDATE SET n=n+1 RETURNING n")
    .bind(h.holder, day)
    .first<{ n: number }>();
  if (!cnt || cnt.n > relayRegPerDay(env)) return { ok: false, code: "rate" };

  const existing = await db.prepare("SELECT holder FROM permits WHERE nk=?1").bind(nk).first<{ holder: string }>();
  if (existing && existing.holder !== h.holder) return { ok: false, code: "auth" };

  const exp = now + L.PERMIT_TTL_S;
  const stmts: D1PreparedStatement[] = [
    db
      .prepare("INSERT INTO permits(nk,rg,e,home,slot,holder,cls,iat) VALUES(?1,?2,?3,?4,?5,?6,?7,?8) ON CONFLICT(nk) DO UPDATE SET rg=?2,e=?3,iat=?8")
      .bind(nk, rg, exp, h.home, h.slot, h.holder, h.cls, now),
    db.prepare("INSERT INTO al_log(rg,op,nk,ts) VALUES(?1,'add',?2,?3)").bind(rg, nk, now),
  ];
  // Keep at most PERMITS_PER_HOLDER live keys per holder (current + previous).
  const olds = await db
    .prepare("SELECT nk, rg FROM permits WHERE holder=?1 AND nk<>?2 ORDER BY iat DESC, nk")
    .bind(h.holder, nk)
    .all<{ nk: string; rg: string }>();
  for (const o of olds.results.slice(L.PERMITS_PER_HOLDER - 1)) {
    stmts.push(db.prepare("DELETE FROM permits WHERE nk=?1").bind(o.nk));
    stmts.push(db.prepare("INSERT INTO al_log(rg,op,nk,ts) VALUES(?1,'del',?2,?3)").bind(o.rg, o.nk, now));
  }
  await db.batch(stmts);
  const seq = await currentSeq(env, rg);
  const s = await signer(env);
  const body = utf8(JSON.stringify({ v: 1, kid: s.kid, nk, rg, exp, cls: h.cls }));
  const tok = b64u(body) + "." + b64u(await s.sign(DOM_PERMIT, body));
  await notifyFeeds(env, [rg]);
  return { ok: true, exp, tok, seq };
}

/** Withdraw permits matching a WHERE clause; returns affected regions. */
async function withdraw(env: Env, where: string, args: unknown[]): Promise<string[]> {
  const db = env.DB;
  const rows = await db.prepare(`SELECT nk, rg FROM permits WHERE ${where}`).bind(...args).all<{ nk: string; rg: string }>();
  if (!rows.results.length) return [];
  const now = nowS();
  const stmts: D1PreparedStatement[] = [];
  for (const r of rows.results) {
    stmts.push(db.prepare("DELETE FROM permits WHERE nk=?1").bind(r.nk));
    stmts.push(db.prepare("INSERT INTO al_log(rg,op,nk,ts) VALUES(?1,'del',?2,?3)").bind(r.rg, r.nk, now));
  }
  await db.batch(stmts);
  const rgs = [...new Set(rows.results.map((r) => r.rg))];
  await notifyFeeds(env, rgs);
  return rgs;
}

export const withdrawKey = (env: Env, holder: string, nk: string) => withdraw(env, "nk=?1 AND holder=?2", [nk, holder]);
export const withdrawSlot = (env: Env, home: string, slot: string) => withdraw(env, "home=?1 AND slot=?2", [home, slot]);
export const withdrawHolder = (env: Env, holder: string) => withdraw(env, "holder=?1", [holder]);

export async function currentSeq(env: Env, rg: string): Promise<number> {
  const r = await env.DB.prepare("SELECT COALESCE(MAX(seq),0) AS s FROM al_log WHERE rg=?1").bind(rg).first<{ s: number }>();
  return r?.s ?? 0;
}

/** Pull-on-change: tell every sidecar subscribed to these regions. */
export async function notifyFeeds(env: Env, rgs: string[]): Promise<void> {
  await Promise.all(
    rgs.map(async (rg) => {
      const seq = await currentSeq(env, rg);
      await env.FEED.get(env.FEED.idFromName(rg)).notify(seq);
    }),
  );
}

export interface AllowlistDoc {
  v: 1;
  kid: string;
  rg: string;
  seq: number;
  since: number;
  iat: number;
  exp: number;
  full: boolean;
  add: { k: string; e: number }[];
  del: string[];
}

export async function buildAllowlist(env: Env, rg: string, since: number) {
  const db = env.DB;
  const now = nowS();
  const seq = await currentSeq(env, rg);
  const s = await signer(env);
  const minRow = await db.prepare("SELECT COALESCE(MIN(seq),0) AS m FROM al_log WHERE rg=?1").bind(rg).first<{ m: number }>();
  const oldest = minRow?.m ?? 0;
  // Delta only if we still hold the whole log since `since`.
  const canDelta = since > 0 && since <= seq && since >= oldest - 1 && oldest > 0;
  const doc: AllowlistDoc = { v: 1, kid: s.kid, rg, seq, since: canDelta ? since : 0, iat: now, exp: now + L.ALLOWLIST_TTL_S, full: !canDelta, add: [], del: [] };
  if (!canDelta) {
    const rows = await db.prepare("SELECT nk, e FROM permits WHERE rg=?1 AND e>?2 ORDER BY nk").bind(rg, now).all<{ nk: string; e: number }>();
    doc.add = rows.results.map((r) => ({ k: r.nk, e: r.e }));
  } else {
    const changed = await db
      .prepare("SELECT DISTINCT nk FROM al_log WHERE rg=?1 AND seq>?2 ORDER BY nk")
      .bind(rg, since)
      .all<{ nk: string }>();
    for (const c of changed.results) {
      const p = await db.prepare("SELECT e FROM permits WHERE nk=?1 AND rg=?2 AND e>?3").bind(c.nk, rg, now).first<{ e: number }>();
      if (p) doc.add.push({ k: c.nk, e: p.e });
      else doc.del.push(c.nk);
    }
  }
  return signEnvelope(s, DOM_ALLOWLIST, doc);
}

/** Hourly housekeeping (cron): drop expired permits, trim the change log. */
export async function prune(env: Env): Promise<void> {
  const now = nowS();
  const db = env.DB;
  const exp = await db.prepare("SELECT nk, rg FROM permits WHERE e<?1").bind(now).all<{ nk: string; rg: string }>();
  const stmts: D1PreparedStatement[] = [];
  for (const r of exp.results) {
    stmts.push(db.prepare("DELETE FROM permits WHERE nk=?1").bind(r.nk));
    stmts.push(db.prepare("INSERT INTO al_log(rg,op,nk,ts) VALUES(?1,'del',?2,?3)").bind(r.rg, r.nk, now));
  }
  // Keep 2 days of log; older `since` values get a full document. Each
  // region's newest row is kept so its seq never goes backwards (the sidecar
  // rejects a lower seq).
  stmts.push(db.prepare("DELETE FROM al_log WHERE ts<?1 AND seq NOT IN (SELECT MAX(seq) FROM al_log GROUP BY rg)").bind(now - 2 * 86400));
  stmts.push(db.prepare("DELETE FROM reg_rate WHERE day<?1").bind(Math.floor(now / 86400) - 1));
  stmts.push(db.prepare("DELETE FROM audit WHERE ts<?1").bind(now - L.AUDIT_KEEP_S));
  await db.batch(stmts);
}
