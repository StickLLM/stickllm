// Copyright (c) 2026 Nink Inc. All rights reserved.
// Revocation: a revoked key dies immediately, and the stick pulls a signed,
// remove-only revoked set over its authenticated session.
import { describe, expect, it } from "vitest";
import V from "../../../vectors/signalling-v2.json";
import { b64u, randomBytes, unb64u } from "../../src/b64";
import { DOM_REVOKED, ed25519Verify } from "../../src/crypto";
import { addSlot, connect, connectStick, helloSig, joinSlot, type M, seedHome, uniqIp } from "../helpers";
import { ROLE_CLIENT } from "../../src/crypto";

const PUB = unb64u(V.signing.pub_b64)!;

async function verifyRevoked(m: any) {
  const body = unb64u(m.body)!;
  expect(m.kid).toBe("test-1");
  expect(await ed25519Verify(PUB, DOM_REVOKED, body, unb64u(m.sig)!)).toBe(true);
  return JSON.parse(new TextDecoder().decode(body));
}

describe("revocation", () => {
  it("slot.del kills the live socket (4403), notifies rev, and the slot can never be re-added", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const s = await addSlot(stick);
    const { c } = await joinSlot(f, s);
    await stick.expect("peer");
    const ok = await stick.req({ t: "slot.del", id: 4, slot: s.slotB });
    expect(ok).toMatchObject({ t: "ok", id: 4, rc: 1 });
    expect((await c.waitClose()).code).toBe(4403);
    expect(await stick.expect("rev")).toMatchObject({ t: "rev", rc: 1, slot: s.slotB, why: "del" });
    expect((await joinSlot(f, s)).reply.code).toBe("auth");
    const again = await stick.req({ t: "slot.add", id: 5, slot: s.slotB, jk: b64u(randomBytes(32)) });
    expect(again.code).toBe("auth");
  });

  it("revoked.get returns a signed body bound to this session's nonce", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const s = await addSlot(stick);
    await stick.req({ t: "slot.del", id: 4, slot: s.slotB }, "ok");
    await stick.expect("rev");
    const m = await stick.req({ t: "revoked.get", id: 6, after: 0 }, "revoked");
    const b = await verifyRevoked(m);
    expect(b).toMatchObject({ v: 1, home: f.homeB, n: b64u(stick.n), after: 0, next: 1, more: false, rc: 1, s: [s.slotB] });
  });

  it("pages 64 at a time with after/next/more", async () => {
    const f = await seedHome();
    let stick = await connectStick(f);
    // 70 revocations (16-slot cap, so add/del in a loop; stay under the rate bucket)
    const all: string[] = [];
    for (let i = 0; i < 70; i++) {
      const s = await addSlot(stick);
      await stick.req({ t: "slot.del", id: 4, slot: s.slotB }, "ok");
      await stick.expect("rev");
      all.push(s.slotB);
      // A fresh session has a fresh 20-message bucket (3 msgs per loop).
      if (i % 5 === 4) stick = await connectStick(f);
    }
    const p1 = await verifyRevoked(await stick.req({ t: "revoked.get", id: 1, after: 0 }, "revoked"));
    expect(p1.s.length).toBe(64);
    expect(p1.more).toBe(true);
    const p2 = await verifyRevoked(await stick.req({ t: "revoked.get", id: 2, after: p1.next }, "revoked"));
    expect(p2.s.length).toBe(6);
    expect(p2.more).toBe(false);
    expect([...p1.s, ...p2.s]).toEqual(all);
    expect(p2.rc).toBe(70);
  }, 30000);

  it("an admin slot client may revoke another slot; a non-admin may not", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const admin = await addSlot(stick, { adm: 1 });
    const plain = await addSlot(stick);
    const victim = await addSlot(stick);
    const p = await joinSlot(f, plain);
    expect((await p.c.req({ t: "slot.del", id: 1, slot: victim.slotB })).code).toBe("auth");
    const a = await joinSlot(f, admin);
    expect(await a.c.req({ t: "slot.del", id: 2, slot: victim.slotB })).toMatchObject({ t: "ok", rc: 1 });
    // Nink 2026-10-29 (Q-S6): the stick hears about an admin's revocation immediately, with the slot.
    expect(await stick.expect("rev")).toMatchObject({ rc: 1, slot: victim.slotB, why: "del" });
  });

  it("revoking a KVM slot also closes that device's other sockets in the home", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const s = await addSlot(stick);
    const { c } = await joinSlot(f, s, { kvm: true });
    // A second, authenticated-but-not-joined socket of the same KVM.
    const c2 = await connect("home=" + f.homeB, uniqIp());
    await c2.req({ t: "hello", id: 1, dev: f.kvmDevB, role: "client", sig: b64u(await helloSig(f.kvmKey, c2.n, f.kvmDev, ROLE_CLIENT, null)) }, "ready");
    await stick.req({ t: "slot.del", id: 4, slot: s.slotB }, "ok");
    expect((await c.waitClose()).code).toBe(4403);
    expect((await c2.waitClose()).code).toBe(4403);
  });
});

describe("audit log (Nink 2026-10-29, Q-S12)", () => {
  it("records who/what/target/result for add, del, rekey, denied and missing ops; no secrets", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const admin = await addSlot(stick, { adm: 1 });
    const plain = await addSlot(stick);
    const victim = await addSlot(stick);
    const rk = b64u(randomBytes(32));
    await stick.req({ t: "slot.rekey", id: 7, slot: victim.slotB, jk: rk }, "ok");
    const p = await joinSlot(f, plain);
    await p.c.req({ t: "slot.del", id: 1, slot: victim.slotB });
    const a = await joinSlot(f, admin);
    await a.c.req({ t: "slot.del", id: 2, slot: victim.slotB }, "ok");
    await stick.req({ t: "slot.del", id: 8, slot: victim.slotB }); // already gone
    const log = await stick.req({ t: "audit.get", id: 9, after: 0 }, "audit");
    const rows = log.rows.map((x: M) => [x.by, x.actor, x.op, x.target, x.res]);
    expect(rows).toEqual([
      ["stick", f.stickDevB, "slot.add", admin.slotB, "ok"],
      ["stick", f.stickDevB, "slot.add", plain.slotB, "ok"],
      ["stick", f.stickDevB, "slot.add", victim.slotB, "ok"],
      ["stick", f.stickDevB, "slot.rekey", victim.slotB, "ok"],
      ["admin", plain.slotB, "slot.del", victim.slotB, "auth"],
      ["admin", admin.slotB, "slot.del", victim.slotB, "ok"],
      ["stick", f.stickDevB, "slot.del", victim.slotB, "nf"],
    ]);
    expect(log.more).toBe(false);
    expect(log.next).toBe(log.rows.at(-1).seq);
    for (const x of log.rows) expect(typeof x.ts).toBe("number");
    const txt = JSON.stringify(log);
    for (const secret of [b64u(admin.jk), b64u(plain.jk), b64u(victim.jk), rk]) expect(txt).not.toContain(secret);
    // Paging and isolation between homes.
    const pg = await stick.req({ t: "audit.get", id: 10, after: 0, limit: 3 }, "audit");
    expect(pg.rows.length).toBe(3);
    expect(pg.more).toBe(true);
    const rest = await stick.req({ t: "audit.get", id: 11, after: pg.next }, "audit");
    expect(rest.rows.length).toBe(4);
    expect((await stick.req({ t: "audit.get", id: 12, limit: 101 })).code).toBe("bad");
    const g = await seedHome();
    const other = await connectStick(g);
    expect((await other.req({ t: "audit.get", id: 1 }, "audit")).rows).toEqual([]);
  });

  it("audit.get is stick-only", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const s = await addSlot(stick, { adm: 1 });
    const { c } = await joinSlot(f, s);
    expect((await c.req({ t: "audit.get", id: 1 })).code).toBe("unknown");
  });

  it("revoked.get is stick-only", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    const s = await addSlot(stick);
    const { c } = await joinSlot(f, s);
    expect((await c.req({ t: "revoked.get", id: 1 })).code).toBe("unknown");
  });
});
