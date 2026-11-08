// Copyright (c) 2026 Nink Inc. All rights reserved.
// HomeDO: one Durable Object per home. Holds the stick socket, slot-joined
// clients, pairing mailboxes (PAIRING-SPEC §4.6), slot table, revoked-peer
// set and per-home pairing rate limits. Hibernatable WebSockets; timers are
// DO alarms only (no setTimeout). No ids, keys or IPs are logged.
import { DurableObject } from "cloudflare:workers";
import { b64u, randomBytes, unb64u } from "./b64";
import { codeModeEnabled, L, relays, SUBPROTOCOL, type Env } from "./config";
import {
  DOM_DEV_HELLO,
  DOM_DEV_ROTATE,
  DOM_REVOKED,
  ed25519Verify,
  helloBody,
  hmacVerify,
  joinInput,
  qrJoinInput,
  ROLE_CLIENT,
  ROLE_SERVER,
  rotateBody,
  signEnvelope,
} from "./crypto";
import { bytes, bytesAs, CONN_RE, err, type Msg, NK_RE, nowS, parse, RID_RE } from "./proto";
import { registerPermit, signer, withdrawHolder, withdrawKey, withdrawSlot } from "./relay";

type Kind = "pre" | "stick" | "client" | "mjoin" | "gone";
type ActorKind = "stick" | "admin" | "device" | "system";
type Route = "dev" | "home" | "rid" | "mbx";

interface Att {
  k: Kind;
  r: Route;
  n: string; // server nonce (welcome.n)
  c: string; // conn id
  dl: number; // auth deadline (ms); 0 once authenticated
  ipk: string; // keyed IP hash, used only to charge the per-IP limiter
  tb: number; // token bucket
  tt: number; // last refill (ms)
  dev?: string; // authenticated device id (hello)
  slot?: string; // joined slot
  mbx?: string; // mailbox (route or joined)
  rid?: string; // routing id from URL (code route)
}

interface SlotRow {
  slot: string;
  jk: string;
  adm: number;
  st: string;
  exp: number;
  fails: number;
  lock: number;
  [k: string]: SqlStorageValue;
}

interface MbxRow {
  mbx: string;
  m: string;
  jk: string | null;
  rid: string | null;
  exp: number;
  [k: string]: SqlStorageValue;
}

export class HomeDO extends DurableObject<Env> {
  private sql: SqlStorage;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`
      CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v);
      CREATE TABLE IF NOT EXISTS slots (slot TEXT PRIMARY KEY, jk TEXT NOT NULL, adm INTEGER NOT NULL,
        st TEXT NOT NULL, exp INTEGER NOT NULL, fails INTEGER NOT NULL DEFAULT 0, lock INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS revoked (seq INTEGER PRIMARY KEY AUTOINCREMENT, slot TEXT NOT NULL UNIQUE, ts INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS mbx (mbx TEXT PRIMARY KEY, m TEXT NOT NULL, jk TEXT, rid TEXT, exp INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS pair_log (ts INTEGER NOT NULL);
    `);
    // Protocol keepalive answered without waking the object.
    ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('{"t":"ping"}', '{"t":"pong"}'));
  }

  // ---------------------------------------------------------------- helpers
  private kvGet<T>(k: string): T | undefined {
    const r = this.sql.exec<{ v: SqlStorageValue }>("SELECT v FROM kv WHERE k=?", k).toArray()[0];
    return r ? (r.v as T) : undefined;
  }
  private kvSet(k: string, v: SqlStorageValue) {
    this.sql.exec("INSERT OR REPLACE INTO kv(k, v) VALUES(?, ?)", k, v);
  }
  private get home(): string {
    return this.kvGet<string>("home")!;
  }
  private nextConn(): string {
    const n = (this.kvGet<number>("cn") ?? 0) + 1;
    this.kvSet("cn", n % 1_000_000);
    return "c" + n;
  }
  private att(ws: WebSocket): Att {
    return ws.deserializeAttachment() as Att;
  }
  private setAtt(ws: WebSocket, a: Att) {
    ws.serializeAttachment(a);
  }
  private sockets(pred: (a: Att) => boolean): [WebSocket, Att][] {
    const out: [WebSocket, Att][] = [];
    for (const ws of this.ctx.getWebSockets()) {
      const a = this.att(ws);
      if (a && pred(a)) out.push([ws, a]);
    }
    return out;
  }
  private stick(): WebSocket | null {
    return this.sockets((a) => a.k === "stick")[0]?.[0] ?? null;
  }
  private send(ws: WebSocket | null, o: unknown) {
    if (!ws) return;
    try {
      ws.send(typeof o === "string" ? o : JSON.stringify(o));
    } catch {
      /* closed */
    }
  }
  private close(ws: WebSocket, code: number, reason: string) {
    const a = this.att(ws);
    if (a && a.k !== "gone") {
      const gone = a.k;
      this.setAtt(ws, { ...a, k: "gone" });
      this.onGone(gone, a);
    }
    try {
      ws.close(code, reason);
    } catch {
      /* closed */
    }
  }

  // ---------------------------------------------------------------- upgrade
  async fetch(req: Request): Promise<Response> {
    const h = req.headers;
    const home = h.get("x-sl-home")!;
    if (!this.kvGet("home")) this.kvSet("home", home);
    const route = h.get("x-sl-route") as Route;
    const mbx = h.get("x-sl-mbx") ?? undefined;
    const now = Date.now();

    if (route === "rid" || route === "mbx") {
      const row = mbx ? this.mbxRow(mbx) : undefined;
      const wantMode = route === "rid" ? "code" : "qr";
      if (!row || row.m !== wantMode || row.exp <= now) return new Response("not found", { status: 404 });
      const n = this.sockets((a) => a.mbx === mbx && (a.k === "mjoin" || a.k === "pre")).length;
      if (n >= L.MBX_CONNS) return new Response("busy", { status: 503 });
    }

    const pair = new WebSocketPair();
    const [client, server] = [pair[0], pair[1]];
    this.ctx.acceptWebSocket(server);
    const nonce = randomBytes(32);
    const a: Att = {
      k: "pre",
      r: route,
      n: b64u(nonce),
      c: this.nextConn(),
      dl: now + (route === "rid" || route === "mbx" ? L.MBX_JOIN_MS : L.UNAUTH_MS),
      ipk: h.get("x-sl-ipk") ?? "",
      tb: L.BURST,
      tt: now,
      mbx,
      rid: h.get("x-sl-rid") ?? undefined,
    };
    if (route === "dev") a.dev = h.get("x-sl-dev") ?? undefined;
    this.setAtt(server, a);
    server.send(JSON.stringify({ t: "welcome", v: 1, n: a.n, now: nowS() }));
    await this.arm();
    return new Response(null, { status: 101, webSocket: client, headers: { "Sec-WebSocket-Protocol": SUBPROTOCOL } });
  }

  // ---------------------------------------------------------------- messages
  async webSocketMessage(ws: WebSocket, raw: string | ArrayBuffer): Promise<void> {
    const a = this.att(ws);
    if (!a || a.k === "gone") return;
    if (typeof raw !== "string") return this.reject(ws, a, "bad");
    if (raw.length > L.FRAME_MAX) {
      this.send(ws, err("size"));
      return this.close(ws, 1009, "size");
    }
    // Token bucket: burst 20, then 1 msg/s per socket.
    const now = Date.now();
    a.tb = Math.min(L.BURST, a.tb + ((now - a.tt) / 1000) * L.RATE_PER_S);
    a.tt = now;
    if (a.tb < 1) {
      this.setAtt(ws, a);
      return this.send(ws, err("rate", undefined, (1 - a.tb) / L.RATE_PER_S));
    }
    a.tb -= 1;
    this.setAtt(ws, a);

    const m = parse(raw);
    if (!m) return this.reject(ws, a, "bad");
    try {
      switch (a.k) {
        case "pre":
          return await this.onPre(ws, a, m);
        case "stick":
          return await this.onStick(ws, a, m);
        case "client":
          return await this.onClient(ws, a, m);
        case "mjoin":
          return this.onMjoin(ws, a, m);
      }
    } catch {
      this.send(ws, err("bad", m.id));
    }
  }

  /** Malformed input: mailbox joiners are dropped (§5); others get err:bad. */
  private reject(ws: WebSocket, a: Att, code: "bad" | "unknown", id?: number) {
    this.send(ws, err(code, id));
    if (a.r === "rid" || a.r === "mbx") this.close(ws, 4400, "bad");
  }

  private async onPre(ws: WebSocket, a: Att, m: Msg) {
    if (m.t === "hello" && (a.r === "dev" || a.r === "home")) return this.hello(ws, a, m);
    if (m.t === "join" && a.r === "home") return this.join(ws, a, m);
    if (m.t === "pair.join" && (a.r === "rid" || a.r === "mbx")) return this.pairJoin(ws, a, m);
    return this.reject(ws, a, "unknown", m.id);
  }

  private async hello(ws: WebSocket, a: Att, m: Msg) {
    const dev = bytes(m, "dev");
    const sig = bytes(m, "sig");
    const role = m.role === "server" ? ROLE_SERVER : m.role === "client" ? ROLE_CLIENT : 0;
    const homeB = m.home === undefined ? null : bytes(m, "home");
    // A v1 HMAC hello ({mac}) has no sig: it is refused as auth (DEV_MASTER scheme removed, Q-S1).
    if (m.sig === undefined && m.mac !== undefined && dev && role) return this.authFail(ws, m.id);
    if (!dev || !sig || !role || (m.home !== undefined && !homeB)) return this.send(ws, err("bad", m.id));
    // Stick route: dev in URL must match, role must be server, home must be ours.
    if (a.r === "dev" && (role !== ROLE_SERVER || b64u(dev) !== a.dev || !homeB || b64u(homeB) !== this.home)) return this.authFail(ws, m.id);
    if (a.r === "home" && role !== ROLE_CLIENT) return this.authFail(ws, m.id);
    const row = await this.env.DB.prepare("SELECT kind, home, status, ak FROM devices WHERE dev=?1")
      .bind(b64u(dev))
      .first<{ kind: string; home: string | null; status: string; ak: string | null }>();
    if (!row || row.status !== "active" || !row.ak) return this.authFail(ws, m.id);
    if (role === ROLE_SERVER && (row.kind !== "stick" || row.home !== this.home)) return this.authFail(ws, m.id);
    const ak = unb64u(row.ak, 32);
    const ok = !!ak && (await ed25519Verify(ak, DOM_DEV_HELLO, helloBody(unb64u(a.n)!, dev, role, role === ROLE_SERVER ? homeB : null), sig));
    if (!ok) return this.authFail(ws, m.id);

    const lim = { frame: L.FRAME_MAX, burst: L.BURST, rate: L.RATE_PER_S };
    const rl = relays(this.env);
    if (role === ROLE_SERVER) {
      // Newest stick connection wins.
      for (const [old] of this.sockets((x) => x.k === "stick")) this.close(old, 4009, "replaced");
      a.k = "stick";
      a.dl = 0;
      a.dev = b64u(dev);
      this.setAtt(ws, a);
      this.send(ws, { t: "ready", id: m.id, v: 1, home: this.home, lim, relays: rl, now: nowS() });
      for (const [c] of this.sockets((x) => x.k === "client")) this.send(c, { t: "peer", conn: "stick", state: "join" });
    } else {
      a.dev = b64u(dev); // still "pre": a client must join a slot next
      this.setAtt(ws, a);
      this.send(ws, { t: "ready", id: m.id, v: 1, lim, relays: rl, now: nowS() });
    }
  }

  private authFail(ws: WebSocket, id?: number) {
    this.send(ws, err("auth", id));
    this.close(ws, 4401, "auth");
  }

  private async join(ws: WebSocket, a: Att, m: Msg) {
    const home = bytes(m, "home");
    const slot = bytes(m, "slot");
    const mac = bytes(m, "mac");
    if (!home || !slot || !mac) return this.send(ws, err("bad", m.id));
    if (b64u(home) !== this.home) return this.authFail(ws, m.id);
    const sid = b64u(slot);
    const now = Date.now();
    const row = this.sql.exec<SlotRow>("SELECT * FROM slots WHERE slot=?", sid).toArray()[0];
    if (!row) return this.authFail(ws, m.id);
    if (row.lock > now) {
      this.send(ws, err("rate", m.id, (row.lock - now) / 1000));
      return this.close(ws, 4429, "rate");
    }
    if (row.st === "pend" && row.exp <= now) return this.authFail(ws, m.id);
    const ok = await hmacVerify(unb64u(row.jk)!, joinInput(unb64u(a.n)!, home, slot), mac);
    if (!ok) {
      const fails = row.fails + 1;
      if (fails >= L.JOIN_FAIL_MAX) this.sql.exec("UPDATE slots SET fails=0, lock=? WHERE slot=?", now + L.JOIN_LOCK_MS, sid);
      else this.sql.exec("UPDATE slots SET fails=? WHERE slot=?", fails, sid);
      return this.authFail(ws, m.id);
    }
    // One live connection per slot: the newer one replaces the older.
    for (const [old] of this.sockets((x) => x.k === "client" && x.slot === sid)) this.close(old, 4009, "replaced");
    if (this.sockets((x) => x.k === "client").length >= L.CLIENTS_MAX) {
      this.send(ws, err("busy", m.id, 30));
      return this.close(ws, 4503, "busy");
    }
    this.sql.exec("UPDATE slots SET fails=0, st='act' WHERE slot=?", sid);
    a.k = "client";
    a.dl = 0;
    a.slot = sid;
    this.setAtt(ws, a);
    const st = this.stick();
    this.send(ws, { t: "joined", id: m.id, conn: a.c, peer: st ? "online" : "offline" });
    this.send(st, { t: "peer", conn: a.c, slot: sid, state: "join" });
  }

  private async pairJoin(ws: WebSocket, a: Att, m: Msg) {
    const row = a.mbx ? this.mbxRow(a.mbx) : undefined;
    const now = Date.now();
    if (!row || row.exp <= now) return this.mbxFail(ws, a, m.id);
    if (a.r === "rid") {
      // The server only ever sees RRRR. Anything else (e.g. a full
      // "RRRR-SSSSSS" pasted by a buggy client) is refused and not retained.
      if (typeof m.rid !== "string" || !RID_RE.test(m.rid) || m.rid !== a.rid || row.m !== "code") return this.mbxFail(ws, a, m.id);
    } else {
      const mb = bytes(m, "mbx");
      const mac = bytes(m, "mac");
      if (!mb || !mac || b64u(mb) !== a.mbx || row.m !== "qr" || !row.jk) return this.mbxFail(ws, a, m.id);
      // Bad MAC drops the connection; it is not an attempt (§4.6).
      if (!(await hmacVerify(unb64u(row.jk)!, qrJoinInput(unb64u(a.n)!, mb), mac))) return this.mbxFail(ws, a, m.id);
    }
    const st = this.stick();
    if (!st) return this.mbxFail(ws, a, m.id);
    a.k = "mjoin";
    a.dl = 0;
    this.setAtt(ws, a);
    this.send(ws, { t: "pair.joined", id: m.id, conn: a.c, home: this.home });
    this.send(st, { t: "peer", conn: a.c, mbx: a.mbx, state: "join" });
  }

  /** Uniform refusal: unknown, expired, closed, wrong mode, bad MAC all look alike. */
  private mbxFail(ws: WebSocket, a: Att, id?: number) {
    if (a.ipk) void this.env.LIMITER.get(this.env.LIMITER.idFromName(a.ipk)).lookupFailed();
    this.send(ws, err("nf", id));
    this.close(ws, 4404, "nf");
  }

  private onMjoin(ws: WebSocket, a: Att, m: Msg) {
    if (m.t !== "pmsg" || typeof m.body !== "string" || m.body.length > L.BOX_MAX || unb64u(m.body) === null) return this.reject(ws, a, "bad", m.id);
    const st = this.stick();
    if (!st) return this.send(ws, err("offline", m.id));
    this.send(st, { t: "pmsg", from: a.c, body: m.body });
  }

  private async onClient(ws: WebSocket, a: Att, m: Msg) {
    switch (m.t) {
      case "sig": {
        if (m.to !== "stick" || !this.validBox(m.box)) return this.send(ws, err("bad", m.id));
        const st = this.stick();
        if (!st) return this.send(ws, err("offline", m.id));
        return this.send(st, { t: "sig", from: a.c, box: m.box });
      }
      case "relay.reg":
        return this.relayReg(ws, a, m);
      case "relay.del":
        return this.relayDel(ws, a, m);
      case "slot.del": {
        const adm = this.sql.exec<{ adm: number }>("SELECT adm FROM slots WHERE slot=?", a.slot!).toArray()[0];
        if (!adm || !adm.adm) {
          const t = bytes(m, "slot");
          await this.audit("admin", a.slot!, "slot.del", t ? b64u(t) : null, "auth");
          return this.send(ws, err("auth", m.id));
        }
        return this.slotDel(ws, m, ["admin", a.slot!]);
      }
      case "auth.rotate":
        return this.authRotate(ws, a, m);
      case "ping":
        return this.send(ws, { t: "pong", id: m.id });
      default:
        return this.send(ws, err("unknown", m.id));
    }
  }

  private async onStick(ws: WebSocket, a: Att, m: Msg) {
    switch (m.t) {
      case "sig": {
        if (typeof m.to !== "string" || !CONN_RE.test(m.to) || !this.validBox(m.box)) return this.send(ws, err("bad", m.id));
        const c = this.sockets((x) => x.k === "client" && x.c === m.to)[0];
        if (!c) return this.send(ws, err("offline", m.id));
        return this.send(c[0], { t: "sig", from: "stick", box: m.box });
      }
      case "pmsg": {
        if (typeof m.to !== "string" || typeof m.body !== "string" || m.body.length > L.BOX_MAX || unb64u(m.body) === null) return this.send(ws, err("bad", m.id));
        const c = this.sockets((x) => x.k === "mjoin" && x.c === m.to)[0];
        if (!c) return this.send(ws, err("offline", m.id));
        return this.send(c[0], { t: "pmsg", body: m.body });
      }
      case "slot.add":
        return this.slotAdd(ws, a, m);
      case "slot.del":
        return this.slotDel(ws, m, ["stick", a.dev!]);
      case "slot.rekey":
        return this.slotRekey(ws, a, m);
      case "audit.get":
        return this.auditGet(ws, m);
      case "auth.rotate":
        return this.authRotate(ws, a, m);
      case "slot.list": {
        const s = this.sql.exec<SlotRow>("SELECT slot, adm, st FROM slots ORDER BY slot").toArray();
        return this.send(ws, { t: "slots", id: m.id, s: s.map((r) => ({ slot: r.slot, adm: r.adm, st: r.st })) });
      }
      case "revoked.get":
        return this.revokedGet(ws, a, m);
      case "pair.open":
        return this.pairOpen(ws, m);
      case "pair.close":
        return this.pairClose(ws, m);
      case "relay.reg":
        return this.relayReg(ws, a, m);
      case "relay.del":
        return this.relayDel(ws, a, m);
      case "ping":
        return this.send(ws, { t: "pong", id: m.id });
      default:
        return this.send(ws, err("unknown", m.id));
    }
  }

  private validBox(b: unknown): boolean {
    return typeof b === "string" && b.length > 0 && b.length <= L.BOX_MAX && unb64u(b) !== null;
  }

  // ---------------------------------------------------------------- slots
  private async slotAdd(ws: WebSocket, a: Att, m: Msg) {
    const slot = bytes(m, "slot");
    const jk = bytes(m, "jk");
    const fail = async (code: "bad" | "auth" | "busy") => {
      await this.audit("stick", a.dev!, "slot.add", slot ? b64u(slot) : null, code);
      return this.send(ws, err(code, m.id));
    };
    if (!slot || !jk) return fail("bad");
    const sid = b64u(slot);
    if (this.sql.exec("SELECT 1 FROM revoked WHERE slot=?", sid).toArray().length) return fail("auth"); // never reuse a revoked id
    if (this.sql.exec("SELECT 1 FROM slots WHERE slot=?", sid).toArray().length) return fail("busy");
    if (this.sql.exec<{ n: number }>("SELECT COUNT(*) AS n FROM slots").one().n >= L.SLOTS_MAX) return fail("busy");
    let st = "act";
    let exp = 0;
    if (m.exp !== undefined) {
      if (!Number.isInteger(m.exp) || (m.exp as number) < 1 || (m.exp as number) > L.SLOT_PENDING_MAX_S) return fail("bad");
      st = "pend";
      exp = Date.now() + (m.exp as number) * 1000;
    }
    this.sql.exec("INSERT INTO slots(slot, jk, adm, st, exp) VALUES(?, ?, ?, ?, ?)", sid, b64u(jk), m.adm === 1 || m.adm === true ? 1 : 0, st, exp);
    await this.audit("stick", a.dev!, "slot.add", sid, "ok");
    this.send(ws, { t: "ok", id: m.id });
    return this.arm();
  }

  private async slotDel(ws: WebSocket, m: Msg, by: [ActorKind, string]) {
    const slot = bytes(m, "slot");
    if (!slot) {
      await this.audit(by[0], by[1], "slot.del", null, "bad");
      return this.send(ws, err("bad", m.id));
    }
    const sid = b64u(slot);
    const existed = this.sql.exec("SELECT 1 FROM slots WHERE slot=?", sid).toArray().length > 0;
    if (!existed) {
      await this.audit(by[0], by[1], "slot.del", sid, "nf");
      return this.send(ws, err("nf", m.id));
    }
    await this.revokeSlot(sid, "del");
    await this.audit(by[0], by[1], "slot.del", sid, "ok");
    this.send(ws, { t: "ok", id: m.id, rc: this.revCounter() });
    this.pushRev(sid, "del"); // after the requester's ok (when the stick asked, it sees ok then rev)
  }

  /** Nink 2026-10-29 (Q-S6): the stick learns of every revocation immediately, with the slot id,
   *  so it can reject new sessions from that peer and tear down live ones. */
  private pushRev(sid: string, why: "del" | "exp") {
    this.send(this.stick(), { t: "rev", rc: this.revCounter(), slot: sid, why });
  }

  /** A revoked key dies immediately: drop the slot's live sockets (and any other socket the same
   *  authenticated device holds in this home), withdraw relay permits, record in the remove-only set. */
  private async revokeSlot(sid: string, why: "del" | "exp") {
    this.sql.exec("DELETE FROM slots WHERE slot=?", sid);
    this.sql.exec("INSERT OR IGNORE INTO revoked(slot, ts) VALUES(?, ?)", sid, nowS());
    const devs = new Set<string>();
    for (const [c, x] of this.sockets((x) => x.k === "client" && x.slot === sid)) {
      if (x.dev) devs.add(x.dev);
      this.close(c, 4403, "revoked");
    }
    if (devs.size) for (const [c] of this.sockets((x) => x.k === "pre" && !!x.dev && devs.has(x.dev))) this.close(c, 4403, "revoked");
    await withdrawSlot(this.env, this.home, sid);
    if (why === "exp") {
      await this.audit("system", "expiry", "slot.expire", sid, "ok");
      this.pushRev(sid, "exp");
    }
  }

  private revCounter(): number {
    return this.sql.exec<{ n: number | null }>("SELECT MAX(seq) AS n FROM revoked").one().n ?? 0;
  }

  private async slotRekey(ws: WebSocket, a: Att, m: Msg) {
    const slot = bytes(m, "slot");
    const jk = bytes(m, "jk");
    if (!slot || !jk) {
      await this.audit("stick", a.dev!, "slot.rekey", slot ? b64u(slot) : null, "bad");
      return this.send(ws, err("bad", m.id));
    }
    const sid = b64u(slot);
    if (!this.sql.exec("SELECT 1 FROM slots WHERE slot=?", sid).toArray().length) {
      await this.audit("stick", a.dev!, "slot.rekey", sid, "nf");
      return this.send(ws, err("nf", m.id));
    }
    this.sql.exec("UPDATE slots SET jk=?, fails=0, lock=0 WHERE slot=?", b64u(jk), sid);
    if (m.cmp === 1 || m.cmp === true) {
      // Compromise-flagged rotation: the old key must stop working now.
      for (const [c] of this.sockets((x) => x.k === "client" && x.slot === sid)) this.close(c, 4403, "rekeyed");
      await withdrawSlot(this.env, this.home, sid);
    }
    await this.audit("stick", a.dev!, m.cmp === 1 || m.cmp === true ? "slot.rekey.cmp" : "slot.rekey", sid, "ok");
    this.send(ws, { t: "ok", id: m.id });
  }

  // ---------------------------------------------------------------- audit (Nink 2026-10-29, Q-S12)
  /** Record one management operation in D1. Public ids and result codes only; never keys,
   *  MACs, jk, PSKs, nonces or IPs. A failed write is retried once in the background and
   *  never blocks a revocation (Q-S22). */
  private async audit(kind: ActorKind, actor: string, op: string, target: string | null, result: string) {
    const st = () =>
      this.env.DB.prepare("INSERT INTO audit(ts,home,actor_kind,actor,op,target,result) VALUES(?1,?2,?3,?4,?5,?6,?7)")
        .bind(nowS(), this.home, kind, actor, op, target, result)
        .run();
    try {
      await st();
    } catch {
      this.ctx.waitUntil(st().then(() => undefined, () => console.error("audit write failed twice")));
    }
  }

  /** Stick-only: page through this home's audit log (oldest first). */
  private async auditGet(ws: WebSocket, m: Msg) {
    const after = m.after === undefined ? 0 : m.after;
    const lim = m.limit === undefined ? L.AUDIT_PAGE : m.limit;
    if (!Number.isInteger(after) || (after as number) < 0 || !Number.isInteger(lim) || (lim as number) < 1 || (lim as number) > L.AUDIT_PAGE)
      return this.send(ws, err("bad", m.id));
    const r = await this.env.DB.prepare(
      "SELECT seq, ts, actor_kind AS ak, actor, op, target, result FROM audit WHERE home=?1 AND seq>?2 ORDER BY seq LIMIT ?3",
    )
      .bind(this.home, after, (lim as number) + 1)
      .all<{ seq: number; ts: number; ak: string; actor: string; op: string; target: string | null; result: string }>();
    const more = r.results.length > (lim as number);
    const rows = r.results.slice(0, lim as number);
    const next = rows.length ? rows[rows.length - 1].seq : (after as number);
    this.send(ws, {
      t: "audit",
      id: m.id,
      next,
      more,
      rows: rows.map((x) => ({ seq: x.seq, ts: x.ts, by: x.ak, actor: x.actor, op: x.op, target: x.target, res: x.result })),
    });
  }

  // ---------------------------------------------------------------- device auth-key rotation (Q-S1)
  /** auth.rotate {ak, pop}: replace this device's server-auth public key. Proof of possession of the
   *  NEW key over this session's nonce, bound to the old key (compare-and-swap in D1). The socket
   *  that rotates stays up; the device's other sockets in this home are closed (4401). */
  private async authRotate(ws: WebSocket, a: Att, m: Msg) {
    if (!a.dev) return this.send(ws, err("auth", m.id)); // phones/desktops join by slot only; no device key
    const nak = bytes(m, "ak");
    const pop = bytes(m, "pop");
    const fail = async (code: "bad" | "auth") => {
      await this.audit("device", a.dev!, "auth.rotate", a.dev!, code);
      return this.send(ws, err(code, m.id));
    };
    if (!nak || !pop) return fail("bad");
    const row = await this.env.DB.prepare("SELECT ak, status FROM devices WHERE dev=?1").bind(a.dev).first<{ ak: string | null; status: string }>();
    const old = row?.ak ? unb64u(row.ak, 32) : null;
    if (!row || row.status !== "active" || !old) return fail("auth");
    if (b64u(nak) === row.ak) return fail("bad");
    if (!(await ed25519Verify(nak, DOM_DEV_ROTATE, rotateBody(unb64u(a.n)!, unb64u(a.dev, 16)!, nak, old), pop))) return fail("auth");
    let changed = 0;
    try {
      const r = await this.env.DB.prepare("UPDATE devices SET ak=?1, gen=gen+1 WHERE dev=?2 AND ak=?3 AND status='active'")
        .bind(b64u(nak), a.dev, row.ak)
        .run();
      changed = r.meta.changes ?? 0;
    } catch {
      return fail("bad"); // e.g. ak already used by another device (unique index)
    }
    if (!changed) return fail("auth"); // raced with another rotation or a disable
    const gen = (await this.env.DB.prepare("SELECT gen FROM devices WHERE dev=?1").bind(a.dev).first<{ gen: number }>())?.gen ?? 0;
    await this.audit("device", a.dev, "auth.rotate", a.dev, "ok");
    for (const [c] of this.sockets((x) => x.dev === a.dev && x.c !== a.c && x.k !== "gone")) this.close(c, 4401, "rotated");
    this.send(ws, { t: "ok", id: m.id, gen });
  }

  private async revokedGet(ws: WebSocket, a: Att, m: Msg) {
    const after = m.after === undefined ? 0 : m.after;
    if (!Number.isInteger(after) || (after as number) < 0) return this.send(ws, err("bad", m.id));
    const rows = this.sql
      .exec<{ seq: number; slot: string }>("SELECT seq, slot FROM revoked WHERE seq>? ORDER BY seq LIMIT ?", after as number, L.REVOKED_PAGE + 1)
      .toArray();
    const more = rows.length > L.REVOKED_PAGE;
    const page = rows.slice(0, L.REVOKED_PAGE);
    const next = page.length ? page[page.length - 1].seq : (after as number);
    const body = { v: 1, home: this.home, n: a.n, after, next, more, rc: this.revCounter(), iat: nowS(), s: page.map((r) => r.slot) };
    const env = await signEnvelope(await signer(this.env), DOM_REVOKED, body);
    this.send(ws, { t: "revoked", id: m.id, ...env });
  }

  // ---------------------------------------------------------------- pairing mailboxes
  private mbxRow(mbx: string): MbxRow | undefined {
    return this.sql.exec<MbxRow>("SELECT * FROM mbx WHERE mbx=?", mbx).toArray()[0];
  }

  private async pairOpen(ws: WebSocket, m: Msg) {
    const mode = m.m;
    if (mode !== "qr" && mode !== "code") return this.send(ws, err("bad", m.id));
    if (mode === "code" && !codeModeEnabled(this.env)) return this.send(ws, err("disabled", m.id)); // §8b(a)
    let jk: Uint8Array | null = null;
    if (mode === "qr") {
      jk = bytes(m, "jk");
      if (!jk) return this.send(ws, err("bad", m.id));
    }
    let exp = m.exp === undefined ? L.MBX_EXP_S : m.exp;
    if (!Number.isInteger(exp) || (exp as number) < 1) return this.send(ws, err("bad", m.id));
    exp = Math.min(exp as number, L.MBX_EXP_S); // never longer than 60 s
    const now = Date.now();

    // Per-home pairing rate: 5 / 10 min, 20 / day, then a 1 h lockout.
    const lock = this.kvGet<number>("plock") ?? 0;
    if (lock > now) return this.send(ws, err("rate", m.id, (lock - now) / 1000));
    this.sql.exec("DELETE FROM pair_log WHERE ts<=?", now - 86_400_000);
    const n10 = this.sql.exec<{ n: number }>("SELECT COUNT(*) AS n FROM pair_log WHERE ts>?", now - 600_000).one().n;
    const nDay = this.sql.exec<{ n: number }>("SELECT COUNT(*) AS n FROM pair_log").one().n;
    if (n10 >= L.PAIR_PER_10MIN || nDay >= L.PAIR_PER_DAY) {
      this.kvSet("plock", now + L.PAIR_LOCK_MS);
      return this.send(ws, err("rate", m.id, L.PAIR_LOCK_MS / 1000));
    }

    const mbx = b64u(randomBytes(8));
    const expMs = now + (exp as number) * 1000;
    const router = this.env.ROUTER.get(this.env.ROUTER.idFromName("global"));
    const r = await router.open(this.home, mbx, expMs, mode === "code");
    if (!r.ok) return this.send(ws, err("busy", m.id, 10));
    this.sql.exec("INSERT INTO pair_log(ts) VALUES(?)", now);
    this.sql.exec("INSERT INTO mbx(mbx, m, jk, rid, exp) VALUES(?, ?, ?, ?, ?)", mbx, mode, jk ? b64u(jk) : null, r.rid ?? null, expMs);
    const reply: Record<string, unknown> = { t: "pair.ok", id: m.id, mbx, exp };
    if (r.rid) reply.rid = r.rid;
    this.send(ws, reply);
    await this.arm();
  }

  private async pairClose(ws: WebSocket, m: Msg) {
    const mb = bytes(m, "mbx");
    if (!mb || (m.why !== "done" && m.why !== "fail" && m.why !== "cancel")) return this.send(ws, err("bad", m.id));
    if (!this.mbxRow(b64u(mb))) return this.send(ws, err("nf", m.id));
    await this.closeMbx(b64u(mb), m.why);
    this.send(ws, { t: "ok", id: m.id });
  }

  /** Closing is final: the mailbox and its routing ID are never reused. */
  private async closeMbx(mbx: string, why: string) {
    this.sql.exec("DELETE FROM mbx WHERE mbx=?", mbx);
    for (const [c] of this.sockets((x) => x.mbx === mbx && (x.k === "mjoin" || x.k === "pre"))) {
      this.send(c, { t: "pair.closed", why });
      this.close(c, 4000, why);
    }
    await this.env.ROUTER.get(this.env.ROUTER.idFromName("global")).release(this.home, mbx);
  }

  // ---------------------------------------------------------------- relay permits
  private async relayReg(ws: WebSocket, a: Att, m: Msg) {
    if (typeof m.nk !== "string" || !NK_RE.test(m.nk) || typeof m.rg !== "string") return this.send(ws, err("bad", m.id));
    const now = nowS();
    const db = this.env.DB;
    const owner = await db
      .prepare("SELECT d.cls, d.ent_until FROM homes h JOIN devices d ON d.dev=h.owner WHERE h.home=?1 AND d.status='active'")
      .bind(this.home)
      .first<{ cls: string; ent_until: number }>();
    let own: { cls: string; ent_until: number } | null = null;
    if (a.dev) own = await db.prepare("SELECT cls, ent_until FROM devices WHERE dev=?1 AND status='active'").bind(a.dev).first();
    let cls: string | null = null;
    if (own && own.cls !== "none" && own.ent_until > now) cls = own.cls;
    else if (owner && owner.cls !== "none" && owner.ent_until > now) cls = owner.cls;
    if (!cls) return this.send(ws, err("auth", m.id)); // no entitlement -> no relay
    const holder = a.dev ?? `${this.home}/${a.slot}`;
    const r = await registerPermit(this.env, { home: this.home, slot: a.k === "client" ? a.slot! : null, holder, cls }, m.nk, m.rg);
    if (!r.ok) return this.send(ws, err(r.code, m.id, r.code === "rate" ? 86400 - (now % 86400) : undefined));
    this.send(ws, { t: "relay.ok", id: m.id, exp: r.exp, tok: r.tok });
  }

  private async relayDel(ws: WebSocket, a: Att, m: Msg) {
    if (typeof m.nk !== "string" || !NK_RE.test(m.nk)) return this.send(ws, err("bad", m.id));
    await withdrawKey(this.env, a.dev ?? `${this.home}/${a.slot}`, m.nk);
    this.send(ws, { t: "ok", id: m.id });
  }

  // ---------------------------------------------------------------- lifecycle
  async webSocketClose(ws: WebSocket, code: number): Promise<void> {
    const a = this.att(ws);
    if (a && a.k !== "gone") {
      this.setAtt(ws, { ...a, k: "gone" });
      this.onGone(a.k, a);
    }
    try {
      ws.close(code === 1005 || code === 1006 ? 1000 : code, "bye");
    } catch {
      /* already closed */
    }
  }

  async webSocketError(ws: WebSocket): Promise<void> {
    return this.webSocketClose(ws, 1011);
  }

  private onGone(kind: Kind, a: Att) {
    if (kind === "client") this.send(this.stick(), { t: "peer", conn: a.c, slot: a.slot, state: "leave" });
    if (kind === "mjoin") this.send(this.stick(), { t: "peer", conn: a.c, mbx: a.mbx, state: "leave" });
    if (kind === "stick") {
      // Mailboxes live only while the stick is connected.
      const open = this.sql.exec<{ mbx: string }>("SELECT mbx FROM mbx").toArray();
      this.ctx.waitUntil(Promise.all(open.map((r) => this.closeMbx(r.mbx, "cancel"))).then(() => undefined));
      for (const [c] of this.sockets((x) => x.k === "client")) this.send(c, { t: "peer", conn: "stick", state: "leave" });
    }
  }

  private async arm() {
    const ds: number[] = [];
    for (const [, a] of this.sockets((x) => x.k === "pre")) ds.push(a.dl);
    const grace = Number(this.env.MBX_GRACE_S ?? 0) * 1000;
    const mb = this.sql.exec<{ t: number | null }>("SELECT MIN(exp) AS t FROM mbx").one().t;
    if (mb) ds.push(mb + grace);
    const sl = this.sql.exec<{ t: number | null }>("SELECT MIN(exp) AS t FROM slots WHERE st='pend'").one().t;
    if (sl) ds.push(sl);
    if (!ds.length) return;
    const t = Math.min(...ds);
    const cur = await this.ctx.storage.getAlarm();
    if (cur === null || cur > t) await this.ctx.storage.setAlarm(t);
  }

  async alarm(): Promise<void> {
    const now = Date.now();
    for (const [ws, a] of this.sockets((x) => x.k === "pre" && x.dl <= now)) {
      this.send(ws, err("auth"));
      this.close(ws, 4408, "timeout");
    }
    const grace = Number(this.env.MBX_GRACE_S ?? 0) * 1000;
    for (const r of this.sql.exec<{ mbx: string }>("SELECT mbx FROM mbx WHERE exp+?<=?", grace, now).toArray()) {
      await this.closeMbx(r.mbx, "exp");
      this.send(this.stick(), { t: "pair.closed", mbx: r.mbx, why: "exp" });
    }
    for (const r of this.sql.exec<{ slot: string }>("SELECT slot FROM slots WHERE st='pend' AND exp<=?", now).toArray()) await this.revokeSlot(r.slot, "exp");
    await this.arm();
  }

  // ---------------------------------------------------------------- test/ops introspection (aggregate only)
  async counters(): Promise<Record<string, number>> {
    const c: Record<string, number> = { stick: 0, client: 0, mjoin: 0, pre: 0 };
    for (const ws of this.ctx.getWebSockets()) {
      const a = this.att(ws);
      if (a && a.k in c) c[a.k]++;
    }
    c.slots = this.sql.exec<{ n: number }>("SELECT COUNT(*) AS n FROM slots").one().n;
    c.mbx = this.sql.exec<{ n: number }>("SELECT COUNT(*) AS n FROM mbx").one().n;
    c.revoked = this.revCounter();
    return c;
  }
}

