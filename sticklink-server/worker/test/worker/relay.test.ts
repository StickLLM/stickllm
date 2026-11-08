// Copyright (c) 2026 Nink Inc. All rights reserved.
// Relay permits, the signed allowlist, the change feed, and revocation sync.
import { SELF } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import V from "../../../vectors/signalling-v2.json";
import { b64u, hex, randomBytes, unb64u } from "../../src/b64";
import { DOM_ALLOWLIST, DOM_PERMIT, ed25519Verify } from "../../src/crypto";
import { prune } from "../../src/relay";
import { addSlot, connectStick, env, joinSlot, relayGet, seedHome } from "../helpers";
import { TEST_RELAY_TOKEN } from "../secrets";

const PUB = unb64u(V.signing.pub_b64)!;
const nk = () => "nodekey:" + hex(randomBytes(32));
const dec = (b: string) => JSON.parse(new TextDecoder().decode(unb64u(b)!));

async function allowlist(since = 0) {
  const r = await relayGet(`/v1/relay/allowlist?rg=tor1&since=${since}`);
  expect(r.status).toBe(200);
  const env_ = (await r.json()) as any;
  expect(await ed25519Verify(PUB, DOM_ALLOWLIST, unb64u(env_.body)!, unb64u(env_.sig)!)).toBe(true);
  return dec(env_.body);
}

describe("relay.reg and permits", () => {
  it("stick with an entitlement gets a signed permit; key appears in the allowlist", async () => {
    const f = await seedHome({ stickCls: "plus" });
    const stick = await connectStick(f);
    const k = nk();
    const r = await stick.req({ t: "relay.reg", id: 1, nk: k, rg: "tor1" }, "relay.ok");
    const [b, s] = r.tok.split(".");
    expect(await ed25519Verify(PUB, DOM_PERMIT, unb64u(b)!, unb64u(s)!)).toBe(true);
    expect(dec(b)).toMatchObject({ v: 1, kid: "test-1", nk: k, rg: "tor1", exp: r.exp, cls: "plus" });
    const al = await allowlist();
    expect(al.full).toBe(true);
    expect(al.add).toContainEqual({ k, e: r.exp });
    expect(al.exp - al.iat).toBe(900);
  });

  it("no entitlement -> err:auth (no relay)", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    expect((await stick.req({ t: "relay.reg", id: 1, nk: nk(), rg: "tor1" })).code).toBe("auth");
  });

  it("unknown region / malformed key -> err:bad", async () => {
    const f = await seedHome({ stickCls: "plus" });
    const stick = await connectStick(f);
    expect((await stick.req({ t: "relay.reg", id: 1, nk: nk(), rg: "nowhere" })).code).toBe("bad");
    expect((await stick.req({ t: "relay.reg", id: 2, nk: "nodekey:XYZ", rg: "tor1" })).code).toBe("bad");
  });

  it("AI KVM uses its own entitlement; a slot-only client uses the owner's", async () => {
    const f = await seedHome({ kvmCls: "kvm" });
    const stick = await connectStick(f);
    const s1 = await addSlot(stick);
    const s2 = await addSlot(stick);
    const kvm = await joinSlot(f, s1, { kvm: true });
    const r = await kvm.c.req({ t: "relay.reg", id: 1, nk: nk(), rg: "tor1" }, "relay.ok");
    expect(dec(r.tok.split(".")[0]).cls).toBe("kvm");
    const phone = await joinSlot(f, s2);
    expect((await phone.c.req({ t: "relay.reg", id: 1, nk: nk(), rg: "tor1" })).code).toBe("auth"); // owner has none
  });

  it("at most 2 live keys per holder: registering a 3rd withdraws the oldest", async () => {
    const f = await seedHome({ stickCls: "plus" });
    const stick = await connectStick(f);
    const ks = [nk(), nk(), nk()];
    for (const [i, k] of ks.entries()) {
      await stick.req({ t: "relay.reg", id: i, nk: k, rg: "tor1" }, "relay.ok");
      await new Promise((r) => setTimeout(r, 1100)); // distinct iat seconds
    }
    const al = await allowlist();
    const keys = al.add.map((a: any) => a.k);
    expect(keys).not.toContain(ks[0]);
    expect(keys).toContain(ks[1]);
    expect(keys).toContain(ks[2]);
  }, 10000);

  it("10 relay.reg per holder per day", async () => {
    const f = await seedHome({ stickCls: "plus" });
    const stick = await connectStick(f);
    for (let i = 0; i < 10; i++) await stick.req({ t: "relay.reg", id: i, nk: nk(), rg: "tor1" }, "relay.ok");
    const r = await stick.req({ t: "relay.reg", id: 99, nk: nk(), rg: "tor1" });
    expect(r.code).toBe("rate");
    expect(r.retry).toBeGreaterThan(0);
  });

  it("a key held by another holder cannot be taken over", async () => {
    const a = await seedHome({ stickCls: "plus" });
    const b = await seedHome({ stickCls: "plus" });
    const sa = await connectStick(a);
    const sb = await connectStick(b);
    const k = nk();
    await sa.req({ t: "relay.reg", id: 1, nk: k, rg: "tor1" }, "relay.ok");
    expect((await sb.req({ t: "relay.reg", id: 1, nk: k, rg: "tor1" })).code).toBe("auth");
    await sb.req({ t: "relay.del", id: 2, nk: k }, "ok"); // no-op for non-holder
    expect((await allowlist()).add.map((x: any) => x.k)).toContain(k);
  });
});

describe("allowlist sync", () => {
  it("delta since seq: adds, then dels after relay.del and slot.del", async () => {
    const f = await seedHome({ stickCls: "plus" });
    const stick = await connectStick(f);
    const s = await addSlot(stick);
    const base = (await allowlist()).seq;
    const kS = nk();
    await stick.req({ t: "relay.reg", id: 1, nk: kS, rg: "tor1" }, "relay.ok");
    const ph = await joinSlot(f, s);
    const kP = nk();
    await ph.c.req({ t: "relay.reg", id: 2, nk: kP, rg: "tor1" }, "relay.ok");
    const d1 = await allowlist(base);
    expect(d1).toMatchObject({ full: false, since: base });
    expect(d1.add.map((a: any) => a.k).sort()).toEqual([kS, kP].sort());
    // relay.del and revocation both withdraw immediately
    await stick.req({ t: "relay.del", id: 3, nk: kS }, "ok");
    await stick.req({ t: "slot.del", id: 4, slot: s.slotB }, "ok");
    const d2 = await allowlist(d1.seq);
    expect(d2.del.sort()).toEqual([kS, kP].sort());
    expect(d2.add).toEqual([]);
    const full = await allowlist();
    expect(full.add.map((a: any) => a.k)).not.toContain(kS);
    expect(full.add.map((a: any) => a.k)).not.toContain(kP);
  });

  it("compromise rekey (cmp) withdraws the slot's permits", async () => {
    const f = await seedHome({ stickCls: "plus" });
    const stick = await connectStick(f);
    const s = await addSlot(stick);
    const ph = await joinSlot(f, s);
    const k = nk();
    await ph.c.req({ t: "relay.reg", id: 2, nk: k, rg: "tor1" }, "relay.ok");
    await stick.req({ t: "slot.rekey", id: 4, slot: s.slotB, jk: b64u(randomBytes(32)), cmp: 1 }, "ok");
    expect((await ph.c.waitClose()).code).toBe(4403);
    expect((await allowlist()).add.map((a: any) => a.k)).not.toContain(k);
  });

  it("a since older than the retained log returns a full document", async () => {
    const f = await seedHome({ stickCls: "plus" });
    const stick = await connectStick(f);
    await stick.req({ t: "relay.reg", id: 1, nk: nk(), rg: "tor1" }, "relay.ok");
    await env.DB.prepare("UPDATE al_log SET ts=0").run();
    await prune(env);
    const cur = (await allowlist()).seq;
    expect(cur).toBeGreaterThan(0); // the region's seq never goes backwards
    expect(cur).toBeGreaterThan(2);
    const d = await allowlist(1); // log before cur was pruned
    expect(d.full).toBe(true);
    expect(d.since).toBe(0);
    const d2 = await allowlist(cur); // still covered
    expect(d2.full).toBe(false);
  });

  it("auth: missing, wrong token, or wrong region -> 401", async () => {
    expect((await relayGet("/v1/relay/allowlist?rg=tor1", null)).status).toBe(401);
    expect((await relayGet("/v1/relay/allowlist?rg=tor1", "wrong-token-0123456789")).status).toBe(401);
    expect((await relayGet("/v1/relay/allowlist?rg=ams1")).status).toBe(401);
    expect((await relayGet("/v1/relay/rev?rg=tor1")).status).toBe(200);
  });

  it("/v1/keys publishes the signing key", async () => {
    const r = (await (await SELF.fetch("https://link.test/v1/keys")).json()) as any;
    expect(r.keys[0]).toEqual({ kid: "test-1", alg: "Ed25519", pub: V.signing.pub_b64 });
  });

  it("feed: pushes chg with the new seq on reg and on revoke (pull-on-change)", async () => {
    const res = await SELF.fetch("https://link.test/v1/relay/feed?rg=tor1", {
      headers: { Upgrade: "websocket", authorization: "Bearer " + TEST_RELAY_TOKEN },
    });
    expect(res.status).toBe(101);
    const ws = res.webSocket!;
    ws.accept();
    const q: any[] = [];
    const waiters: ((m: any) => void)[] = [];
    ws.addEventListener("message", (e) => {
      const m = JSON.parse(String(e.data));
      const w = waiters.shift();
      w ? w(m) : q.push(m);
    });
    const next = () => (q.length ? Promise.resolve(q.shift()) : new Promise<any>((r) => waiters.push(r)));
    const first = await next();
    expect(first.t).toBe("chg");
    const f = await seedHome({ stickCls: "plus" });
    const stick = await connectStick(f);
    const k = nk();
    await stick.req({ t: "relay.reg", id: 1, nk: k, rg: "tor1" }, "relay.ok");
    const c1 = await next();
    expect(c1.seq).toBeGreaterThan(first.seq);
    await stick.req({ t: "relay.del", id: 2, nk: k }, "ok");
    const c2 = await next();
    expect(c2.seq).toBeGreaterThan(c1.seq);
    ws.send('{"t":"ping"}');
    expect(await next()).toEqual({ t: "pong" });
    ws.close(1000);
  });
});
