// Copyright (c) 2026 Nink Inc. All rights reserved.
// Device auth, slot joins, sig forwarding, framing, caps and timeouts.
import { runDurableObjectAlarm, runInDurableObject } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { b64u, randomBytes, unb64u } from "../../src/b64";
import { ROLE_CLIENT, ROLE_SERVER } from "../../src/crypto";
import { addSlot, connect, connectStick, edSign, env, helloSig, homeStub, joinSlot, type M, newAuthKey, rotatePop, seedHome, sleep, upgrade, uniqIp } from "../helpers";
import IK from "../../../vectors/ikpsk2-v2.json";

describe("stick hello (Ed25519 device server-auth, Q-S1)", () => {
  it("accepts a valid signature and returns home, limits and relays", async () => {
    const f = await seedHome();
    const c = await connect("dev=" + f.stickDevB, uniqIp());
    const sig = await helloSig(f.stickKey, c.n, f.stickDev, ROLE_SERVER, f.home);
    const r = await c.req({ t: "hello", id: 7, dev: f.stickDevB, role: "server", home: f.homeB, sig: b64u(sig) }, "ready");
    expect(r).toMatchObject({ id: 7, v: 1, home: f.homeB, lim: { frame: 4096, burst: 20, rate: 1 } });
    expect(r.relays[0].rg).toBe("tor1");
    c.close();
  });

  it("rejects a bad signature, a replayed signature (fresh nonce), a wrong role and a wrong key", async () => {
    const f = await seedHome();
    const c1 = await connect("dev=" + f.stickDevB, uniqIp());
    const good = await helloSig(f.stickKey, c1.n, f.stickDev, ROLE_SERVER, f.home);
    c1.send({ t: "hello", dev: f.stickDevB, role: "server", home: f.homeB, sig: b64u(randomBytes(64)) });
    expect((await c1.next()).code).toBe("auth");
    expect((await c1.waitClose()).code).toBe(4401);
    // Replay the signature made for c1's nonce on a new connection.
    const c2 = await connect("dev=" + f.stickDevB, uniqIp());
    c2.send({ t: "hello", dev: f.stickDevB, role: "server", home: f.homeB, sig: b64u(good) });
    expect((await c2.next()).code).toBe("auth");
    // Client-role signature on the stick route.
    const c3 = await connect("dev=" + f.stickDevB, uniqIp());
    const cs = await helloSig(f.stickKey, c3.n, f.stickDev, ROLE_CLIENT, null);
    c3.send({ t: "hello", dev: f.stickDevB, role: "client", sig: b64u(cs) });
    expect((await c3.next()).code).toBe("auth");
    // Another device's key (the KVM's) over the right input.
    const c4 = await connect("dev=" + f.stickDevB, uniqIp());
    const ks = await helloSig(f.kvmKey, c4.n, f.stickDev, ROLE_SERVER, f.home);
    c4.send({ t: "hello", dev: f.stickDevB, role: "server", home: f.homeB, sig: b64u(ks) });
    expect((await c4.next()).code).toBe("auth");
  });

  it("refuses the removed v1 HMAC hello and devices without an auth key", async () => {
    const f = await seedHome();
    const c1 = await connect("dev=" + f.stickDevB, uniqIp());
    c1.send({ t: "hello", dev: f.stickDevB, role: "server", home: f.homeB, mac: b64u(randomBytes(32)) });
    expect((await c1.next()).code).toBe("auth");
    expect((await c1.waitClose()).code).toBe(4401);
    await env.DB.prepare("UPDATE devices SET ak=NULL WHERE dev=?1").bind(f.stickDevB).run();
    const c2 = await connect("dev=" + f.stickDevB, uniqIp());
    const sig = await helloSig(f.stickKey, c2.n, f.stickDev, ROLE_SERVER, f.home);
    c2.send({ t: "hello", dev: f.stickDevB, role: "server", home: f.homeB, sig: b64u(sig) });
    expect((await c2.next()).code).toBe("auth");
    expect((await c2.waitClose()).code).toBe(4401);
  });

  it("auth.rotate: proof of possession of the new key, CAS on the old key, other sockets closed, audited", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const next = await newAuthKey();
    // Bad PoP (signed by the old key) is refused.
    const badPop = await edSign(f.stickKey, "sl1/dev-rotate/v1", new Uint8Array(112));
    expect((await stick.req({ t: "auth.rotate", id: 20, ak: b64u(next.pub), pop: b64u(badPop) })).code).toBe("auth");
    const pop = await rotatePop(next, stick.n, f.stickDev, f.stickKey.pub);
    const r = await stick.req({ t: "auth.rotate", id: 21, ak: b64u(next.pub), pop: b64u(pop) }, "ok");
    expect(r.gen).toBe(1);
    const row = await env.DB.prepare("SELECT ak, gen FROM devices WHERE dev=?1").bind(f.stickDevB).first<{ ak: string; gen: number }>();
    expect(row).toEqual({ ak: b64u(next.pub), gen: 1 });
    // The same PoP cannot be replayed (old key no longer matches).
    expect((await stick.req({ t: "auth.rotate", id: 22, ak: b64u(next.pub), pop: b64u(pop) })).code).toBe("bad");
    // Old key no longer authenticates; the new one does.
    const o = await connect("dev=" + f.stickDevB, uniqIp());
    o.send({ t: "hello", dev: f.stickDevB, role: "server", home: f.homeB, sig: b64u(await helloSig(f.stickKey, o.n, f.stickDev, ROLE_SERVER, f.home)) });
    expect((await o.next()).code).toBe("auth");
    const fresh = await connectStick(f, uniqIp(), next);
    const log = await fresh.req({ t: "audit.get", id: 23 }, "audit");
    const rot = log.rows.filter((x: M) => x.op === "auth.rotate").map((x: M) => x.res);
    expect(rot).toEqual(["auth", "ok", "bad"]);
    expect(JSON.stringify(log)).not.toContain(b64u(pop));
    fresh.close();
  });

  it("an AI KVM can rotate its key after joining; a phone (no device key) cannot", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const s = await addSlot(stick);
    const { c } = await joinSlot(f, s, { kvm: true });
    const next = await newAuthKey();
    const pop = await rotatePop(next, c.n, f.kvmDev, f.kvmKey.pub);
    expect((await c.req({ t: "auth.rotate", id: 9, ak: b64u(next.pub), pop: b64u(pop) })).t).toBe("ok");
    const s2 = await addSlot(stick);
    const { c: phone, reply } = await joinSlot(f, s2);
    expect(reply.t).toBe("joined");
    expect((await phone.req({ t: "auth.rotate", id: 9, ak: b64u(next.pub), pop: b64u(pop) })).code).toBe("auth");
  });

  it("unknown device / home routes are 404", async () => {
    expect((await upgrade("dev=" + b64u(randomBytes(16)), uniqIp())).status).toBe(404);
    expect((await upgrade("home=" + b64u(randomBytes(16)), uniqIp())).status).toBe(404);
    expect((await upgrade("dev=short", uniqIp())).status).toBe(404);
  });

  it("requires the sticklink.1 subprotocol", async () => {
    const { SELF } = await import("cloudflare:test");
    const r = await SELF.fetch("https://link.test/v1/ws?home=x", { headers: { Upgrade: "websocket", "CF-Connecting-IP": uniqIp() } });
    expect(r.status).toBe(400);
  });

  it("a newer stick connection replaces the older (4009)", async () => {
    const f = await seedHome();
    const a = await connectStick(f);
    const b = await connectStick(f);
    expect((await a.waitClose()).code).toBe(4009);
    expect((await b.req({ t: "slot.list", id: 1 }, "slots")).s).toEqual([]);
  });

  it("unauthenticated sockets are closed at the 10 s deadline (alarm)", async () => {
    const f = await seedHome();
    const c = await connect("home=" + f.homeB, uniqIp());
    await runInDurableObject(homeStub(f), (_i, st) => {
      for (const ws of st.getWebSockets()) {
        const a = ws.deserializeAttachment();
        if (a.k === "pre") ws.serializeAttachment({ ...a, dl: Date.now() - 1 });
      }
    });
    expect(await runDurableObjectAlarm(homeStub(f))).toBe(true);
    expect((await c.waitClose()).code).toBe(4408);
  });
});

describe("slot join and signalling", () => {
  it("joins, then forwards sig both ways; peer events reach the stick", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const s = await addSlot(stick);
    const { c, reply } = await joinSlot(f, s);
    expect(reply).toMatchObject({ t: "joined", peer: "online" });
    expect(reply.conn).toMatch(/^c\d+$/);
    expect(await stick.expect("peer")).toMatchObject({ conn: reply.conn, slot: s.slotB, state: "join" });
    c.send({ t: "sig", to: "stick", box: "AAEC" });
    expect(await stick.expect("sig")).toEqual({ t: "sig", from: reply.conn, box: "AAEC" });
    stick.send({ t: "sig", to: reply.conn, box: "AwQF" });
    expect(await c.expect("sig")).toEqual({ t: "sig", from: "stick", box: "AwQF" });
    c.close();
    expect(await stick.expect("peer")).toMatchObject({ conn: reply.conn, state: "leave" });
  });

  it("AI KVM: hello(role client) then join; frames stay small", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const s = await addSlot(stick);
    const { c, reply } = await joinSlot(f, s, { kvm: true });
    expect(reply.t).toBe("joined");
    c.send({ t: "sig", to: "stick", box: b64u(randomBytes(148)) }); // IKpsk2 msg1 size
    const got = await stick.expect("sig");
    expect(JSON.stringify(got).length).toBeLessThan(260);
  });

  it("AI KVM: the ikpsk2-v2 sig vector frame (243 B) is forwarded byte-for-byte", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const s = await addSlot(stick);
    const { c } = await joinSlot(f, s, { kvm: true });
    const frame = JSON.parse(IK.box.wire_sig);
    expect(IK.box.wire_sig.length).toBe(243);
    c.send(frame);
    const got = await stick.expect("sig");
    expect(got.box).toBe(IK.box.box_b64);
    expect(unb64u(got.box)!.length).toBe(IK.box.box_len);
  });

  it("client sees offline when the stick is away, and online when it arrives", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const s = await addSlot(stick);
    stick.close();
    await sleep(50);
    const { c, reply } = await joinSlot(f, s);
    expect(reply.peer).toBe("offline");
    c.send({ t: "sig", to: "stick", box: "AAEC" });
    expect((await c.next()).code).toBe("offline");
    await connectStick(f);
    expect(await c.expect("peer")).toEqual({ t: "peer", conn: "stick", state: "join" });
  });

  it("5 bad join MACs lock the slot for 15 min, even for the right MAC", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const s = await addSlot(stick);
    for (let i = 0; i < 5; i++) {
      const { reply } = await joinSlot(f, s, { badMac: true });
      expect(reply.code).toBe("auth");
    }
    const { c, reply } = await joinSlot(f, s);
    expect(reply.code).toBe("rate");
    expect(reply.retry).toBeGreaterThan(890);
    expect((await c.waitClose()).code).toBe(4429);
    // slot.rekey clears the lock
    await stick.req({ t: "slot.rekey", id: 9, slot: s.slotB, jk: b64u(s.jk) }, "ok");
    expect((await joinSlot(f, s)).reply.t).toBe("joined");
  });

  it("one live connection per slot: the newer replaces the older", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const s = await addSlot(stick);
    const a = await joinSlot(f, s);
    const b = await joinSlot(f, s);
    expect(b.reply.t).toBe("joined");
    expect((await a.c.waitClose()).code).toBe(4009);
  });

  it("caps: 16 slots per home, 8 live clients per home", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const slots = [];
    for (let i = 0; i < 16; i++) slots.push(await addSlot(stick));
    const r = await stick.req({ t: "slot.add", id: 5, slot: b64u(randomBytes(8)), jk: b64u(randomBytes(32)) });
    expect(r.code).toBe("busy");
    for (let i = 0; i < 8; i++) expect((await joinSlot(f, slots[i])).reply.t).toBe("joined");
    const ninth = await joinSlot(f, slots[8]);
    expect(ninth.reply.code).toBe("busy");
    expect((await ninth.c.waitClose()).code).toBe(4503);
  });

  it("pending slot auto-revokes at expiry", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const s = await addSlot(stick, { exp: 300 });
    await runInDurableObject(homeStub(f), (_i, st) => {
      st.storage.sql.exec("UPDATE slots SET exp=? WHERE st='pend'", Date.now() - 1);
    });
    await runDurableObjectAlarm(homeStub(f));
    expect(await stick.expect("rev")).toMatchObject({ rc: 1, slot: s.slotB, why: "exp" });
    expect((await joinSlot(f, s)).reply.code).toBe("auth");
    const log = await stick.req({ t: "audit.get", id: 30 }, "audit");
    expect(log.rows.at(-1)).toMatchObject({ by: "system", actor: "expiry", op: "slot.expire", target: s.slotB, res: "ok" });
  });
});

describe("framing", () => {
  it("frames over 4096 bytes get err:size and close 1009", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    stick.send({ t: "sig", to: "c1", box: "A".repeat(5000) });
    expect((await stick.next()).code).toBe("size");
    expect((await stick.waitClose()).code).toBe(1009);
  });

  it("token bucket: burst 20, then err:rate with retry", async () => {
    const f = await seedHome();
    const stick = await connectStick(f); // hello used 1 token
    for (let i = 0; i < 25; i++) stick.send({ t: "slot.list", id: 100 + i });
    const got = [];
    for (let i = 0; i < 25; i++) got.push(await stick.next());
    const rate = got.filter((m) => m.t === "err" && m.code === "rate");
    expect(got.filter((m) => m.t === "slots").length).toBeGreaterThanOrEqual(19);
    expect(rate.length).toBeGreaterThanOrEqual(4);
    expect(rate[0].retry).toBeGreaterThanOrEqual(1);
  });

  it("unknown t -> err:unknown; malformed JSON -> err:bad; ping is auto-answered", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    expect(await stick.req({ t: "nope", id: 3 })).toEqual({ t: "err", code: "unknown", id: 3 });
    stick.send("{not json");
    expect((await stick.next()).code).toBe("bad");
    stick.send('{"t":"ping"}');
    expect(await stick.next()).toEqual({ t: "pong" });
  });
});
