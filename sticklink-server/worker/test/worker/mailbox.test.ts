// Copyright (c) 2026 Nink Inc. All rights reserved.
// Pairing mailboxes (PAIRING-SPEC §4.6): QR mode, code mode (flag on in this
// project), one attempt, expiry, caps, stick-disconnect, and the rule that the
// server never sees the secret half (SSSSSS) of a code.
import { env as rawEnv, runDurableObjectAlarm, runInDurableObject } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { b64u, randomBytes } from "../../src/b64";
import { hkdf } from "../../src/crypto";
import { connect, connectStick, env, homeStub, qrJoin, routerStub, RX_LOG, seedHome, sleep, uniqIp, upgrade } from "../helpers";

async function openQr(stick: any, exp = 60) {
  const secret = randomBytes(32);
  const jk = await hkdf(secret, "sl1/qr-join");
  const ok = await stick.req({ t: "pair.open", id: 11, m: "qr", jk: b64u(jk), exp }, "pair.ok");
  return { jk, mbx: ok.mbx as string, ok };
}

describe("QR mailbox", () => {
  it("joins with the right MAC; pmsg flows both ways; pair.close done ends it", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const { jk, mbx, ok } = await openQr(stick);
    expect(ok.exp).toBe(60);
    expect(ok.rid).toBeUndefined();
    const { c, reply } = await qrJoin(mbx, jk);
    expect(reply).toMatchObject({ t: "pair.joined", home: f.homeB });
    expect(await stick.expect("peer")).toMatchObject({ conn: reply.conn, mbx, state: "join" });
    c.send({ t: "pmsg", body: "cGFrZTE" });
    expect(await stick.expect("pmsg")).toEqual({ t: "pmsg", from: reply.conn, body: "cGFrZTE" });
    stick.send({ t: "pmsg", to: reply.conn, body: "cGFrZTI" });
    expect(await c.expect("pmsg")).toEqual({ t: "pmsg", body: "cGFrZTI" });
    await stick.req({ t: "pair.close", id: 12, mbx, why: "done" }, "ok");
    expect(await c.expect("pair.closed")).toEqual({ t: "pair.closed", why: "done" });
    expect((await upgrade("mbx=" + mbx, uniqIp())).status).toBe(404); // never reused
  });

  it("a bad MAC drops that connection but does not consume the mailbox", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const { jk, mbx } = await openQr(stick);
    const bad = await qrJoin(mbx, jk, { badMac: true });
    expect(bad.reply).toEqual({ t: "err", code: "nf", id: 1 });
    expect((await bad.c.waitClose()).code).toBe(4404);
    expect((await qrJoin(mbx, jk)).reply.t).toBe("pair.joined");
  });

  it("pair.close fail: one attempt, later joiners get 404 and live joiners get pair.closed", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const { jk, mbx } = await openQr(stick);
    const { c } = await qrJoin(mbx, jk);
    await stick.req({ t: "pair.close", id: 13, mbx, why: "fail" }, "ok");
    expect((await c.expect("pair.closed")).why).toBe("fail");
    expect((await upgrade("mbx=" + mbx, uniqIp())).status).toBe(404);
  });

  it("at most 4 connections per mailbox", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const { mbx } = await openQr(stick);
    for (let i = 0; i < 4; i++) await connect("mbx=" + mbx, uniqIp());
    expect((await upgrade("mbx=" + mbx, uniqIp())).status).toBe(503);
  });

  it("mailbox joiners must pair.join within 5 s; anything else drops them", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const { mbx } = await openQr(stick);
    const c = await connect("mbx=" + mbx, uniqIp());
    c.send({ t: "sig", to: "stick", box: "AA" });
    expect((await c.next()).code).toBe("unknown");
    expect((await c.waitClose()).code).toBe(4400);
  });

  it("closes with cancel when the stick disconnects", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const { jk, mbx } = await openQr(stick);
    const { c } = await qrJoin(mbx, jk);
    stick.close();
    expect((await c.expect("pair.closed")).why).toBe("cancel");
    await sleep(20);
    expect((await upgrade("mbx=" + mbx, uniqIp())).status).toBe(404);
  });

  it("exp is capped at 60 s", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    expect((await openQr(stick, 600)).ok.exp).toBe(60);
  });
});

describe("code mailbox (FEATURE_SPAKE2_CODE=1)", () => {
  it("rid flow; the server never sees SSSSSS (wire + every store)", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const ok = await stick.req({ t: "pair.open", id: 21, m: "code", exp: 60 }, "pair.ok");
    expect(ok.rid).toMatch(/^\d{4}$/);
    // The stick displays RRRR-SSSSSS; SSSSSS stays on the devices.
    const S = String(100000 + Math.floor(Math.random() * 900000)).slice(0, 6);
    const code = `${ok.rid}-${S}`;
    // A buggy joiner that pastes the whole code into the URL: refused, not routed.
    expect((await upgrade("rid=" + encodeURIComponent(code), uniqIp())).status).toBe(404);
    // ...or into pair.join: refused, mailbox unharmed.
    const buggy = await connect("rid=" + ok.rid, uniqIp());
    buggy.send({ t: "pair.join", id: 1, rid: code });
    expect((await buggy.next()).code).toBe("nf");
    // Correct joiner: only RRRR.
    const j = await connect("rid=" + ok.rid, uniqIp());
    const r = await j.req({ t: "pair.join", id: 2, rid: ok.rid }, "pair.joined");
    expect(r.home).toBe(f.homeB);
    // SPAKE2 messages are opaque to the server.
    j.send({ t: "pmsg", body: b64u(randomBytes(33)) });
    const pm = await stick.expect("pmsg");
    stick.send({ t: "pmsg", to: pm.from, body: b64u(randomBytes(33)) });
    await j.expect("pmsg");
    // One attempt: stick reports failure, the code is dead.
    await stick.req({ t: "pair.close", id: 22, mbx: ok.mbx, why: "fail" }, "ok");
    expect((await upgrade("rid=" + ok.rid, uniqIp())).status).toBe(404);

    // Audit: SSSSSS appears in no server-sent frame and in no server store.
    for (const fr of RX_LOG) expect(fr.includes(S)).toBe(false);
    const dump = async (stub: any) =>
      runInDurableObject(stub, (_i: unknown, st: DurableObjectState) => {
        const out: string[] = [];
        const tables = st.storage.sql.exec<{ name: string }>("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '_cf_%' AND name NOT LIKE 'sqlite_%'").toArray();
        for (const t of tables) for (const row of st.storage.sql.exec(`SELECT * FROM "${t.name}"`).toArray()) out.push(JSON.stringify(row));
        return out.join("\n");
      });
    expect(await dump(homeStub(f))).not.toContain(S);
    expect(await dump(routerStub())).not.toContain(S);
    for (const t of ["devices", "homes", "permits", "al_log", "reg_rate"]) {
      const rows = await env.DB.prepare(`SELECT * FROM ${t}`).all();
      expect(JSON.stringify(rows.results)).not.toContain(S);
    }
  });

  it("expiry closes the mailbox, tells the stick, and releases the rid into the 10-min hold", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const ok = await stick.req({ t: "pair.open", id: 23, m: "code" }, "pair.ok");
    const j = await connect("rid=" + ok.rid, uniqIp());
    await j.req({ t: "pair.join", id: 2, rid: ok.rid }, "pair.joined");
    await runInDurableObject(homeStub(f), (_i, st) => {
      st.storage.sql.exec("UPDATE mbx SET exp=?", Date.now() - 1);
    });
    await runDurableObjectAlarm(homeStub(f));
    expect(await j.expect("pair.closed")).toEqual({ t: "pair.closed", why: "exp" });
    expect(await stick.expect("pair.closed")).toEqual({ t: "pair.closed", mbx: ok.mbx, why: "exp" });
    expect((await upgrade("rid=" + ok.rid, uniqIp())).status).toBe(404);
    const held = await runInDurableObject(routerStub(), (_i, st) =>
      st.storage.sql.exec("SELECT until FROM rid_hold WHERE rid=?", ok.rid).toArray(),
    );
    expect(held.length).toBe(1);
    expect(Number(held[0].until)).toBeGreaterThan(Date.now() + 9 * 60_000);
  });

  it("a mailbox connection does not consume the invitation", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const ok = await stick.req({ t: "pair.open", id: 24, m: "code" }, "pair.ok");
    const a = await connect("rid=" + ok.rid, uniqIp());
    a.close();
    await sleep(20);
    const b = await connect("rid=" + ok.rid, uniqIp());
    expect((await b.req({ t: "pair.join", id: 2, rid: ok.rid })).t).toBe("pair.joined");
  });

  it("per-home pairing rate: 5 per 10 min across stick sessions, then a 1 h lock", async () => {
    const f = await seedHome();
    for (let i = 0; i < 5; i++) {
      const s = await connectStick(f); // new session every time
      const ok = await s.req({ t: "pair.open", id: 30 + i, m: "code" }, "pair.ok");
      await s.req({ t: "pair.close", id: 40 + i, mbx: ok.mbx, why: "cancel" }, "ok");
      s.close();
    }
    const s = await connectStick(f);
    const r = await s.req({ t: "pair.open", id: 50, m: "qr", jk: b64u(randomBytes(32)) });
    expect(r.code).toBe("rate");
    expect(r.retry).toBe(3600);
    const r2 = await s.req({ t: "pair.open", id: 51, m: "qr", jk: b64u(randomBytes(32)) });
    expect(r2.code).toBe("rate");
  });

  it("per-home pairing rate: 20 per day", async () => {
    const f = await seedHome();
    const s = await connectStick(f);
    await runInDurableObject(homeStub(f), (_i, st) => {
      for (let i = 0; i < 20; i++) st.storage.sql.exec("INSERT INTO pair_log(ts) VALUES(?)", Date.now() - 3 * 3600_000 - i);
    });
    expect((await s.req({ t: "pair.open", id: 52, m: "code" })).code).toBe("rate");
  });
});

describe("per-IP limits on mailbox lookups", () => {
  it("10 mailbox connections per minute per IP", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const ip = uniqIp();
    const codes: number[] = [];
    for (let i = 0; i < 11; i++) codes.push((await upgrade("mbx=" + b64u(randomBytes(8)), ip)).status);
    expect(codes.slice(0, 10).every((c) => c === 404)).toBe(true);
    expect(codes[10]).toBe(429);
    stick.close();
  });

  it("after 100 failed lookups the IP is blocked: even a live mailbox is 404", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const { mbx } = await openQr(stick);
    const ip = uniqIp();
    const { ipKey } = await import("../../src/crypto");
    const lim: any = env.LIMITER.get(env.LIMITER.idFromName(await ipKey((rawEnv as any).IP_PEPPER, ip)));
    for (let i = 0; i < 100; i++) await lim.lookupFailed();
    expect((await upgrade("mbx=" + mbx, ip)).status).toBe(404);
    expect((await upgrade("mbx=" + mbx, uniqIp())).status).toBe(101);
  });

  it("30 upgrades per minute per IP", async () => {
    const f = await seedHome();
    const ip = uniqIp();
    let last = 0;
    for (let i = 0; i < 31; i++) {
      const r = await upgrade("home=" + f.homeB, ip);
      last = r.status;
      if (r.webSocket) {
        r.webSocket.accept();
        r.webSocket.close(1000);
      }
    }
    expect(last).toBe(429);
  });
});
