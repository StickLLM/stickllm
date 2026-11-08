// Copyright (c) 2026 Nink Inc. All rights reserved.
// Cross-session per-IP limits.
import { runDurableObjectAlarm, runInDurableObject as rido } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { env } from "../helpers";

let k = 0;
const fresh = (): any => env.LIMITER.get(env.LIMITER.idFromName("lim-test-" + k++));
const T = Date.now();
const runInDurableObject = rido as any; // avoids TS2589 on the RPC stub type

describe("per-IP limiter", () => {
  it("30 upgrades/min, then retry-after until the window rolls", async () => {
    const l = fresh();
    for (let i = 0; i < 30; i++) expect(await l.hit(["upgrade"], T + i)).toBe(0);
    expect(await l.hit(["upgrade"], T + 100)).toBeGreaterThan(0);
    expect(await l.hit(["upgrade"], T + 60_001)).toBe(0);
  });

  it("10 mailbox connections/min", async () => {
    const l = fresh();
    for (let i = 0; i < 10; i++) expect(await l.hit(["upgrade", "mbx"], T + i)).toBe(0);
    expect(await l.hit(["upgrade", "mbx"], T + 20)).toBeGreaterThan(0);
  });

  it("100 failed lookups/hour block the IP for an hour", async () => {
    const l = fresh();
    for (let i = 0; i < 99; i++) await l.lookupFailed(T + i);
    expect(await l.blockedFor(T + 100)).toBe(0);
    await l.lookupFailed(T + 101);
    expect(await l.blockedFor(T + 102)).toBe(3600);
    expect(await l.hit(["upgrade"], T + 103)).toBeGreaterThan(0);
    expect(await l.blockedFor(T + 3_600_200)).toBe(0);
  });

  it("wipes its state once windows lapse (no long-term per-IP data)", async () => {
    const l = fresh();
    await l.hit(["upgrade"], Date.now() - 120_000);
    await runInDurableObject(l, async (_i: any, st: DurableObjectState) => {
      const s: any = await st.storage.get("s");
      s.w.upgrade.s = Date.now() - 120_000;
      await st.storage.put("s", s);
    });
    // force reload from storage then run the alarm
    await runInDurableObject(l as any, (i: any) => {
      i.st = null;
    });
    await runDurableObjectAlarm(l);
    await runInDurableObject(l, async (_i: any, st: DurableObjectState) => expect((await st.storage.list()).size).toBe(0));
  });
});
