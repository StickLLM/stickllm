// Copyright (c) 2026 Nink Inc. All rights reserved.
// End-to-end check against LOCAL processes started by run.sh:
//   wrangler dev --local (:8787)  ->  sticklink-admit (:9099)  ->  derper -dev (:3340)
// Uses the deterministic fixtures from worker/fixtures/dev-fixtures.json.
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { b64u, unb64u, hmac, helloSig, joinInput } from "../worker/scripts/lib.mjs";

const require = createRequire(new URL("../worker/package.json", import.meta.url));
const WebSocket = require("ws");
const BASE = process.env.SL_BASE ?? "ws://127.0.0.1:8787";
const PROBE = process.env.SL_PROBE;
const DERP = process.env.SL_DERP ?? "http://127.0.0.1:3340/derp";
const fx = JSON.parse(readFileSync(new URL("../worker/fixtures/dev-fixtures.json", import.meta.url)));
let failed = 0;
const ok = (cond, what) => { console.log(`${cond ? "PASS" : "FAIL"} ${what}`); if (!cond) failed++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class C {
  constructor(ws) { this.ws = ws; this.q = []; this.w = []; ws.on("message", (d) => { const m = JSON.parse(String(d)); const f = this.w.shift(); f ? f(m) : this.q.push(m); }); }
  static async open(query) {
    const ws = new WebSocket(`${BASE}/v1/ws?${query}`, "sticklink.1");
    await new Promise((res, rej) => { ws.once("open", res); ws.once("error", rej); ws.once("unexpected-response", (_q, r) => rej(new Error("HTTP " + r.statusCode))); });
    const c = new C(ws);
    const w = await c.next();
    c.n = unb64u(w.n);
    return c;
  }
  next(ms = 5000) { const m = this.q.shift(); if (m) return Promise.resolve(m); return new Promise((res, rej) => { const t = setTimeout(() => rej(new Error("timeout")), ms); this.w.push((x) => { clearTimeout(t); res(x); }); }); }
  async req(o) { this.ws.send(JSON.stringify(o)); for (;;) { const m = await this.next(); if (m.id === o.id) return m; } }
  close() { this.ws.close(1000); }
}

function probe(priv) {
  try { return execFileSync(PROBE, ["-url", DERP, "-key", priv], { encoding: "utf8" }).trim(); }
  catch (e) { return String(e.stdout || "").trim() || "REJECTED"; }
}
function genkey() { const [priv, pub] = execFileSync(PROBE, ["-genkey"], { encoding: "utf8" }).trim().split(" "); return { priv, pub }; }
async function eventually(fn, want, ms = 8000) { const end = Date.now() + ms; let r; do { r = fn(); if (r.startsWith(want)) return r; await sleep(300); } while (Date.now() < end); return r; }

const s1 = fx.devices.stick1, k1 = fx.devices.kvm1, kslot = fx.peers.kvm1_slot;

// 1. stick hello
const stick = await C.open("dev=" + s1.dev);
let sig = helloSig(unb64u(s1.auth_seed), stick.n, unb64u(s1.dev), 1, unb64u(s1.home));
let r = await stick.req({ t: "hello", id: 1, dev: s1.dev, role: "server", home: s1.home, sig: b64u(sig) });
ok(r.t === "ready" && r.home === s1.home, "stick hello -> ready");
r = await stick.req({ t: "slot.add", id: 2, slot: kslot.slot, jk: kslot.jk });
ok(r.t === "ok", "stick slot.add (kvm slot)");

// 2. KVM hello + join (network initiator)
const kvm = await C.open("home=" + s1.home);
sig = helloSig(unb64u(k1.auth_seed), kvm.n, unb64u(k1.dev), 2, null);
r = await kvm.req({ t: "hello", id: 1, dev: k1.dev, role: "client", sig: b64u(sig) });
ok(r.t === "ready", "kvm hello -> ready");
const joinMsg = JSON.stringify({ t: "join", id: 3, home: s1.home, slot: kslot.slot, mac: b64u(hmac(unb64u(kslot.jk), joinInput(kvm.n, unb64u(s1.home), unb64u(kslot.slot)))) });
ok(joinMsg.length < 160, `kvm join frame ${joinMsg.length} B < 160`);
kvm.ws.send(joinMsg);
r = await kvm.next();
ok(r.t === "joined", "kvm join -> joined");

// 3. relay permits
const A = genkey(), B = genkey(), X = genkey();
r = await stick.req({ t: "relay.reg", id: 10, nk: A.pub, rg: "tor1" });
ok(r.t === "relay.ok" && typeof r.tok === "string", "stick relay.reg -> relay.ok (signed permit)");
r = await kvm.req({ t: "relay.reg", id: 11, nk: B.pub, rg: "tor1" });
ok(r.t === "relay.ok", "kvm relay.reg -> relay.ok (own kvm entitlement)");

ok((await eventually(() => probe(A.priv), "ADMITTED")) === "ADMITTED", "derper admits stick key after relay.reg");
ok((await eventually(() => probe(B.priv), "ADMITTED")) === "ADMITTED", "derper admits kvm key after relay.reg");
ok(probe(X.priv).startsWith("REJECTED"), "derper rejects an unregistered key");

// 4. withdrawals propagate (feed chg -> delta pull)
r = await stick.req({ t: "relay.del", id: 12, nk: A.pub });
ok(r.t === "ok", "stick relay.del");
ok((await eventually(() => probe(A.priv), "REJECTED")).startsWith("REJECTED"), "derper rejects stick key after relay.del");
r = await stick.req({ t: "slot.del", id: 13, slot: kslot.slot });
ok(r.t === "ok", "stick slot.del (revoke kvm)");
ok((await eventually(() => probe(B.priv), "REJECTED")).startsWith("REJECTED"), "derper rejects kvm key after slot.del");
ok(probe(X.priv).startsWith("REJECTED"), "unregistered key still rejected");

// 5. a key registered now, for the fail-closed step run.sh does after us
const D = genkey();
r = await stick.req({ t: "relay.reg", id: 14, nk: D.pub, rg: "tor1" });
ok((await eventually(() => probe(D.priv), "ADMITTED")) === "ADMITTED", "fresh key admitted");
stick.close(); kvm.close();
if (process.env.SL_LAST_KEY_FILE) (await import("node:fs")).writeFileSync(process.env.SL_LAST_KEY_FILE, D.priv, { mode: 0o600 });
console.log(failed ? `${failed} FAILED` : "ALL PASS");
process.exit(failed ? 1 : 0);
