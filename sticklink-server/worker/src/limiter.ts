// Copyright (c) 2026 Nink Inc. All rights reserved.
// Cross-session per-IP limits (PAIRING-SPEC §5, SIGNALLING-PLAN §2.4).
// One LimiterDO per keyed hash of the client IP: the raw IP is never stored,
// and the object wipes itself once all its windows have lapsed.
import { DurableObject } from "cloudflare:workers";
import { L, type Env } from "./config";

export type LimitKind = "upgrade" | "mbx" | "lookupfail";

const RULES: Record<LimitKind, { window: number; max: number }> = {
  upgrade: { window: 60_000, max: L.UPGRADES_PER_MIN },
  mbx: { window: 60_000, max: L.MBX_CONN_PER_MIN },
  lookupfail: { window: 3_600_000, max: L.LOOKUP_FAIL_PER_H },
};

interface State {
  w: Record<string, { s: number; n: number }>;
  blocked: number;
}

export class LimiterDO extends DurableObject<Env> {
  private st: State | null = null;

  private async load(): Promise<State> {
    if (!this.st) this.st = (await this.ctx.storage.get<State>("s")) ?? { w: {}, blocked: 0 };
    return this.st;
  }

  /** Returns 0 if allowed, else seconds until retry. */
  async hit(kinds: LimitKind[], now = Date.now()): Promise<number> {
    const st = await this.load();
    if (st.blocked > now) return Math.ceil((st.blocked - now) / 1000);
    let retry = 0;
    for (const k of kinds) {
      const r = RULES[k];
      let w = st.w[k];
      if (!w || now - w.s >= r.window) w = st.w[k] = { s: now, n: 0 };
      w.n++;
      if (w.n > r.max) retry = Math.max(retry, Math.ceil((w.s + r.window - now) / 1000));
    }
    await this.save(now);
    return retry;
  }

  /** Is the IP currently blocked for routing-ID lookups? */
  async blockedFor(now = Date.now()): Promise<number> {
    const st = await this.load();
    return st.blocked > now ? Math.ceil((st.blocked - now) / 1000) : 0;
  }

  /** Record a failed routing-ID / mailbox lookup; 100/h blocks the IP for 1 h. */
  async lookupFailed(now = Date.now()): Promise<void> {
    const st = await this.load();
    const r = RULES.lookupfail;
    let w = st.w.lookupfail;
    if (!w || now - w.s >= r.window) w = st.w.lookupfail = { s: now, n: 0 };
    w.n++;
    if (w.n >= r.max) st.blocked = now + L.LOOKUP_BLOCK_MS;
    await this.save(now);
  }

  private async save(now: number): Promise<void> {
    await this.ctx.storage.put("s", this.st);
    const until = Math.max(this.st!.blocked, ...Object.entries(this.st!.w).map(([k, w]) => w.s + RULES[k as LimitKind].window));
    await this.ctx.storage.setAlarm(Math.max(until, now) + 1000);
  }

  async alarm(): Promise<void> {
    const st = await this.load();
    const now = Date.now();
    const live = st.blocked > now || Object.entries(st.w).some(([k, w]) => now - w.s < RULES[k as LimitKind].window);
    if (live) return this.save(now);
    this.st = null;
    await this.ctx.storage.deleteAll();
  }
}
