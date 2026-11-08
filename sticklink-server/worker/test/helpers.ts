// Copyright (c) 2026 Nink Inc. All rights reserved.
// Test client: a minimal sl1 client over SELF.fetch WebSockets.
import { env as rawEnv, SELF } from "cloudflare:test";
import type { Env } from "../src/config";
import { b64u, randomBytes, unb64u } from "../src/b64";
import { DOM_DEV_HELLO, DOM_DEV_ROTATE, hmac, helloBody, joinInput, qrJoinInput, ROLE_CLIENT, ROLE_SERVER, rotateBody, signedInput } from "../src/crypto";
import { TEST_RELAY_TOKEN } from "./secrets";

export type M = Record<string, any>;
export const env = rawEnv as unknown as Env;

/** Every frame any test client sent or received, for the secret-half audit. */
export const WIRE_LOG: string[] = [];
/** Only frames the server sent to test clients. */
export const RX_LOG: string[] = [];

export class Client {
  q: M[] = [];
  waiters: ((m: M) => void)[] = [];
  closed: { code: number; reason: string } | null = null;
  closeWaiters: (() => void)[] = [];
  n!: Uint8Array;
  constructor(public ws: WebSocket) {
    ws.addEventListener("message", (e) => {
      WIRE_LOG.push(String(e.data));
      RX_LOG.push(String(e.data));
      const m = JSON.parse(String(e.data));
      const w = this.waiters.shift();
      if (w) w(m);
      else this.q.push(m);
    });
    ws.addEventListener("close", (e) => {
      this.closed = { code: e.code, reason: e.reason };
      for (const w of this.closeWaiters.splice(0)) w();
    });
  }
  send(o: M | string) {
    const s = typeof o === "string" ? o : JSON.stringify(o);
    WIRE_LOG.push(s);
    this.ws.send(s);
  }
  next(ms = 3000): Promise<M> {
    const m = this.q.shift();
    if (m) return Promise.resolve(m);
    return new Promise((res, rej) => {
      const t = setTimeout(() => rej(new Error("timeout waiting for message")), ms);
      this.waiters.push((x) => {
        clearTimeout(t);
        res(x);
      });
    });
  }
  async expect(t: string, ms = 3000): Promise<M> {
    for (;;) {
      const m = await this.next(ms);
      if (m.t === t) return m;
      if (m.t === "err" && t !== "err") throw new Error("got err " + JSON.stringify(m) + " waiting for " + t);
    }
  }
  /** Send a request and wait for the reply with the same id (or the next
   *  message if no id). Unsolicited events seen meanwhile stay queued. */
  async req(o: M, t?: string): Promise<M> {
    this.send(o);
    const stash: M[] = [];
    let m: M;
    for (;;) {
      m = await this.next();
      if (o.id === undefined || m.id === o.id || (m.t === "err" && m.id === undefined)) break;
      stash.push(m);
    }
    this.q.unshift(...stash);
    if (t && m.t !== t) throw new Error(`expected ${t}, got ${JSON.stringify(m)}`);
    return m;
  }
  waitClose(ms = 3000): Promise<{ code: number; reason: string }> {
    if (this.closed) return Promise.resolve(this.closed);
    return new Promise((res, rej) => {
      const t = setTimeout(() => rej(new Error("timeout waiting for close")), ms);
      this.closeWaiters.push(() => {
        clearTimeout(t);
        res(this.closed!);
      });
    });
  }
  close() {
    try {
      this.ws.close(1000, "done");
    } catch {}
  }
}

export async function upgrade(query: string, ip = "198.51.100.1"): Promise<Response> {
  return SELF.fetch("https://link.test/v1/ws?" + query, {
    headers: { Upgrade: "websocket", "Sec-WebSocket-Protocol": "sticklink.1", "CF-Connecting-IP": ip },
  });
}

export async function connect(query: string, ip?: string): Promise<Client> {
  const res = await upgrade(query, ip);
  if (res.status !== 101 || !res.webSocket) throw new Error("upgrade failed: " + res.status);
  res.webSocket.accept();
  const c = new Client(res.webSocket);
  const w = await c.next();
  if (w.t !== "welcome") throw new Error("no welcome");
  c.n = unb64u(w.n, 32)!;
  return c;
}

let ipCounter = 1;
export const uniqIp = () => `2001:db8:${(ipCounter++).toString(16)}::1`; // one /64 each (limits bucket by /64)

export interface Fixture {
  home: Uint8Array;
  homeB: string;
  stickDev: Uint8Array;
  stickDevB: string;
  kvmDev: Uint8Array;
  kvmDevB: string;
  stickKey: AuthKey;
  kvmKey: AuthKey;
}

/** A device's Ed25519 server-auth keypair (generated "on the device"; D1 gets only `pub`). */
export interface AuthKey {
  sk: CryptoKey;
  pub: Uint8Array;
}
export async function newAuthKey(): Promise<AuthKey> {
  const kp = (await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"])) as CryptoKeyPair;
  return { sk: kp.privateKey, pub: new Uint8Array((await crypto.subtle.exportKey("raw", kp.publicKey)) as ArrayBuffer) };
}
export async function edSign(k: AuthKey, domain: string, body: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, k.sk, signedInput(domain, body)));
}
export async function helloSig(k: AuthKey, n: Uint8Array, dev: Uint8Array, role: number, home: Uint8Array | null) {
  return edSign(k, DOM_DEV_HELLO, helloBody(n, dev, role, home));
}
export async function rotatePop(newK: AuthKey, n: Uint8Array, dev: Uint8Array, oldPub: Uint8Array) {
  return edSign(newK, DOM_DEV_ROTATE, rotateBody(n, dev, newK.pub, oldPub));
}

/** Seed a home with its stick, plus one AI KVM device. */
export async function seedHome(opts: { stickCls?: string; kvmCls?: string } = {}): Promise<Fixture> {
  const home = randomBytes(16);
  const stickDev = randomBytes(16);
  const kvmDev = randomBytes(16);
  const now = Math.floor(Date.now() / 1000);
  const ent = (c?: string) => (c && c !== "none" ? now + 86400 * 30 : 0);
  const stickKey = await newAuthKey();
  const kvmKey = await newAuthKey();
  await env.DB.batch([
    env.DB.prepare("INSERT INTO devices(dev,kind,gen,home,status,cls,ent_until,created,ak) VALUES(?1,'stick',0,?2,'active',?3,?4,?5,?6)").bind(
      b64u(stickDev), b64u(home), opts.stickCls ?? "none", ent(opts.stickCls), now, b64u(stickKey.pub)),
    env.DB.prepare("INSERT INTO homes(home,owner,created) VALUES(?1,?2,?3)").bind(b64u(home), b64u(stickDev), now),
    env.DB.prepare("INSERT INTO devices(dev,kind,gen,home,status,cls,ent_until,created,ak) VALUES(?1,'kvm',0,NULL,'active',?2,?3,?4,?5)").bind(
      b64u(kvmDev), opts.kvmCls ?? "none", ent(opts.kvmCls), now, b64u(kvmKey.pub)),
  ]);
  return { home, homeB: b64u(home), stickDev, stickDevB: b64u(stickDev), kvmDev, kvmDevB: b64u(kvmDev), stickKey, kvmKey };
}

export async function connectStick(f: Fixture, ip = uniqIp(), key: AuthKey = f.stickKey): Promise<Client> {
  const c = await connect("dev=" + f.stickDevB, ip);
  const sig = await helloSig(key, c.n, f.stickDev, ROLE_SERVER, f.home);
  const r = await c.req({ t: "hello", id: 1, dev: f.stickDevB, role: "server", home: f.homeB, sig: b64u(sig) }, "ready");
  if (r.home !== f.homeB) throw new Error("home mismatch");
  return c;
}

export async function addSlot(stick: Client, opts: { adm?: number; exp?: number } = {}) {
  const slot = randomBytes(8);
  const jk = randomBytes(32);
  const r = await stick.req({ t: "slot.add", id: 2, slot: b64u(slot), jk: b64u(jk), ...opts });
  if (r.t !== "ok") throw new Error("slot.add failed " + JSON.stringify(r));
  return { slot, jk, slotB: b64u(slot) };
}

export async function joinSlot(f: Fixture, s: { slot: Uint8Array; jk: Uint8Array }, opts: { ip?: string; kvm?: boolean; badMac?: boolean } = {}) {
  const c = await connect("home=" + f.homeB, opts.ip ?? uniqIp());
  if (opts.kvm) {
    const sig = await helloSig(f.kvmKey, c.n, f.kvmDev, ROLE_CLIENT, null);
    await c.req({ t: "hello", id: 1, dev: f.kvmDevB, role: "client", sig: b64u(sig) }, "ready");
  }
  let mac = await hmac(s.jk, joinInput(c.n, f.home, s.slot));
  if (opts.badMac) mac = randomBytes(32);
  c.send({ t: "join", id: 3, home: f.homeB, slot: b64u(s.slot), mac: b64u(mac) });
  return { c, reply: await c.next() };
}

export async function qrJoin(mbxB: string, jkQr: Uint8Array, opts: { ip?: string; badMac?: boolean } = {}) {
  const c = await connect("mbx=" + mbxB, opts.ip ?? uniqIp());
  let mac = await hmac(jkQr, qrJoinInput(c.n, unb64u(mbxB, 8)!));
  if (opts.badMac) mac = randomBytes(32);
  c.send({ t: "pair.join", id: 1, mbx: mbxB, mac: b64u(mac) });
  return { c, reply: await c.next() };
}

export function relayGet(path: string, token: string | null = TEST_RELAY_TOKEN) {
  const headers: Record<string, string> = {};
  if (token) headers.authorization = "Bearer " + token;
  return SELF.fetch("https://link.test" + path, { headers });
}

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export const homeStub = (f: Fixture) => env.HOME.get(env.HOME.idFromName(f.homeB));
export const routerStub = () => env.ROUTER.get(env.ROUTER.idFromName("global"));
