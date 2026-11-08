// Copyright (c) 2026 Nink Inc. All rights reserved.
// Routing-ID allocation (PAIRING-SPEC §4.6): uniqueness while live, 10-min
// release hold, 24-h per-home no-reuse, busy when exhausted, expiry.
import { runDurableObjectAlarm, runInDurableObject } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { env } from "../helpers";
import type { RouterDO } from "../../src/router";

let k = 0;
const fresh = () => env.ROUTER.get(env.ROUTER.idFromName("router-test-" + k++));
const MIN = 60_000;

describe("routing IDs", () => {
  it("are 4 digits and unique among live mailboxes", async () => {
    const r = fresh();
    const now = Date.now();
    const seen = new Set<string>();
    for (let i = 0; i < 300; i++) {
      const o = await r.open("home" + i, "mbx" + i, now + MIN, true, now);
      expect(o.ok).toBe(true);
      expect(o.rid).toMatch(/^[0-9]{4}$/);
      expect(seen.has(o.rid!)).toBe(false);
      seen.add(o.rid!);
    }
  });

  it("lookup works while live, fails after expiry, and the rid is held 10 min", async () => {
    const r = fresh();
    const now = Date.now();
    const o = await r.open("H", "M", now + MIN, true, now);
    expect(await r.lookupRid(o.rid!, now + 1000)).toEqual({ home: "H", mbx: "M" });
    expect(await r.lookupRid(o.rid!, now + MIN)).toBeNull(); // expired
    await r.stats(now + MIN); // gc -> released into hold
    await runInDurableObject(r, (inst: RouterDO, st) => {
      const held = st.storage.sql.exec("SELECT until FROM rid_hold WHERE rid=?", o.rid!).toArray();
      expect(held.length).toBe(1);
      expect(held[0].until).toBe(now + MIN + 10 * MIN);
    });
  });

  it("never re-issues a released rid within 10 min, nor to the same home within 24 h", async () => {
    const r = fresh();
    const now = Date.now();
    // Exhaust all but two values via the hold table, then check the exclusions.
    await runInDurableObject(r, (_i: RouterDO, st) => {
      for (let v = 0; v < 10000; v++) {
        const s = v.toString().padStart(4, "0");
        if (s !== "1111" && s !== "2222") st.storage.sql.exec("INSERT INTO rid_hold(rid, until) VALUES(?, ?)", s, now + 9 * MIN);
      }
    });
    const a = await r.open("homeA", "m1", now + MIN, true, now);
    expect(["1111", "2222"]).toContain(a.rid);
    await r.release("homeA", "m1", now + 1000); // released -> 10-min hold
    const b = await r.open("homeA", "m2", now + MIN, true, now + 2000);
    const other = a.rid === "1111" ? "2222" : "1111";
    expect(b.rid).toBe(other);
    // Everything else is live or held now -> busy.
    expect((await r.open("homeB", "m3", now + MIN, true, now + 3000)).ok).toBe(false);
    // After the bulk hold lapses (9 min) other homes get values again, but
    // homeA still cannot get its own two recent rids for 24 h.
    await r.release("homeA", "m2", now + 4000);
    const t = now + 11 * MIN;
    const c = await r.open("homeB", "m4", t + MIN, true, t);
    expect(c.ok).toBe(true);
    for (let i = 0; i < 50; i++) {
      const d = await r.open("homeA", "x" + i, t + MIN, true, t);
      expect([a.rid, b.rid]).not.toContain(d.rid);
    }
  });

  it("allocation is uniform over free values (chi-square on leading digit)", async () => {
    const r = fresh();
    let t = Date.now();
    const buckets = new Array(10).fill(0);
    const N = 2000;
    for (let i = 0; i < N; i++) {
      const o = await r.open("h" + i, "m" + i, t + 1000, true, t);
      buckets[Number(o.rid![0])]++;
      await r.release("h" + i, "m" + i, t);
      t += 11 * MIN; // hold lapses
    }
    const exp = N / 10;
    const chi = buckets.reduce((s, b) => s + (b - exp) ** 2 / exp, 0);
    expect(chi).toBeLessThan(27.9); // p ≈ 0.001, 9 dof
  });

  it("only the owning home can release; QR mailboxes have no rid", async () => {
    const r = fresh();
    const now = Date.now();
    const q = await r.open("H", "Q", now + MIN, false, now);
    expect(q.rid).toBeUndefined();
    expect(await r.lookupMbx("Q", now)).toEqual({ home: "H" });
    await r.release("OTHER", "Q", now);
    expect(await r.lookupMbx("Q", now)).toEqual({ home: "H" });
    await r.release("H", "Q", now);
    expect(await r.lookupMbx("Q", now)).toBeNull();
  });

  it("alarm expires mailboxes", async () => {
    const r = fresh();
    const now = Date.now();
    await r.open("H", "E", now - 1, true, now - 2);
    await runDurableObjectAlarm(r);
    expect((await r.stats()).live).toBe(0);
  });
});
