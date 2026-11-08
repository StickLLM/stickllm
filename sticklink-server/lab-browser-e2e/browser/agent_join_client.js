/* Lab: Method C pair → Noise DC → StickLink app-mux (APP-MUX-V1.md). */
import { x25519 } from "@noble/curves/ed25519.js";
import { chacha20poly1305 } from "@noble/ciphers/chacha.js";
import { sha256 } from "@noble/hashes/sha2.js";
import { hmac } from "@noble/hashes/hmac.js";
import { hkdf } from "@noble/hashes/hkdf.js";
import { createAppMux, installBrowserTransport } from "./sticklink_app_mux.js";

const te = new TextEncoder();
const td = new TextDecoder();
const b64u = (u8) => btoa(String.fromCharCode(...u8)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const unb64u = (s, n) => {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const u = Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + pad), (c) => c.charCodeAt(0));
  if (n != null && u.length !== n) throw new Error("b64 len");
  return u;
};
const cat = (...a) => {
  const o = new Uint8Array(a.reduce((x, y) => x + y.length, 0));
  let i = 0;
  for (const p of a) { o.set(p, i); i += p.length; }
  return o;
};
const encB = (x) => {
  const b = typeof x === "string" ? te.encode(x) : x;
  const h = new Uint8Array(2);
  new DataView(h.buffer).setUint16(0, b.length);
  return cat(h, b);
};
const hkdf0 = (ikm, info) => hkdf(sha256, ikm, new Uint8Array(0), info, 32);
const u32be = (n) => {
  const b = new Uint8Array(4);
  new DataView(b.buffer).setUint32(0, n);
  return b;
};

function parseQr(raw) {
  if (!raw.startsWith("sl1:")) throw new Error("not sl1");
  const q = new URLSearchParams(raw.slice(4));
  const M = q.get("M");
  if (!/^[0-9a-fA-F]{16}$/.test(M)) throw new Error("M");
  const mbx = Uint8Array.from(M.match(/../g).map((h) => parseInt(h, 16)));
  return { mbx, mbxB: b64u(mbx), K: unb64u(q.get("K"), 32), P: unb64u(q.get("P"), 32), E: Number(q.get("E")) };
}

function noiseNonce(n) {
  const b = new Uint8Array(12);
  new DataView(b.buffer).setBigUint64(4, BigInt(n), true);
  return b;
}
function aead(key, n, ad, data, encrypt) {
  const c = chacha20poly1305(key, noiseNonce(n), ad);
  return encrypt ? c.encrypt(data) : c.decrypt(data);
}
function noiseHkdf(ck, ikm, nOut) {
  const t = hmac(sha256, ck, ikm);
  const o1 = hmac(sha256, t, new Uint8Array([1]));
  const o2 = hmac(sha256, t, cat(o1, new Uint8Array([2])));
  if (nOut === 2) return [o1, o2];
  return [o1, o2, hmac(sha256, t, cat(o2, new Uint8Array([3])))];
}

class Sym {
  constructor(prologue) {
    const name = te.encode("Noise_IKpsk2_25519_ChaChaPoly_SHA256");
    this.h = name.length > 32 ? sha256(name) : cat(name, new Uint8Array(32 - name.length));
    this.ck = this.h.slice();
    this.k = null;
    this.n = 0;
    this.mixHash(prologue);
  }
  mixHash(d) { this.h = sha256(cat(this.h, d)); }
  mixKey(ikm) {
    const [ck, k] = noiseHkdf(this.ck, ikm, 2);
    this.ck = ck; this.k = k; this.n = 0;
  }
  mixKeyAndHash(ikm) {
    const [ck, t, k] = noiseHkdf(this.ck, ikm, 3);
    this.ck = ck; this.mixHash(t); this.k = k; this.n = 0;
  }
  encHash(pt) {
    const ct = this.k ? aead(this.k, this.n++, this.h, pt, true) : pt;
    this.mixHash(ct);
    return ct;
  }
  decHash(ct) {
    const pt = this.k ? aead(this.k, this.n++, this.h, ct, false) : ct;
    this.mixHash(ct);
    return pt;
  }
  split() { return noiseHkdf(this.ck, new Uint8Array(0), 2); }
}

function qrPrologue(home, mbx, stickPub) {
  return cat(te.encode("sl1/qr"), new Uint8Array([1]), home, mbx, stickPub);
}
function derivePairPsk({ rI, rR, prior, hh, th, iStatic, rStatic, epoch = 0 }) {
  const info = cat(te.encode("sl1/pair-psk/v1"), iStatic, rStatic, u32be(epoch));
  return hkdf(sha256, cat(rI, rR, prior), cat(hh, th), info, 32);
}
function confirmMac(kc, role, hh) {
  return hmac(sha256, kc, cat(te.encode("sl1/pair-confirm/" + role), hh));
}

export async function runPairCAgent({ wsUrl, qr, log, iceServers, stopAfterJoined = false }) {
  const L = (m) => { log?.(m); console.log("[agent-join]", m); };
  const q = parseQr(qr);
  const invite = q.P, stickPub = q.K, mbx = q.mbx, mbxB = q.mbxB;
  const jk = hkdf0(invite, te.encode("sl1/qr-join"));

  const ws = new WebSocket(`${wsUrl}?mbx=${encodeURIComponent(mbxB)}`, "sticklink.1");
  const inbox = [];
  let waiters = [];
  ws.addEventListener("message", (e) => {
    const m = JSON.parse(e.data);
    const w = waiters.shift();
    if (w) w(m); else inbox.push(m);
  });
  const next = (ms = 60000) => new Promise((res, rej) => {
    if (inbox.length) return res(inbox.shift());
    const t = setTimeout(() => rej(new Error("timeout")), ms);
    waiters.push((m) => { clearTimeout(t); res(m); });
  });
  await new Promise((r, j) => {
    ws.onopen = r;
    ws.onerror = () => j(new Error("ws: cannot open StickLink signalling (mailbox expired/unknown, or network blocked)"));
    ws.onclose = (ev) => {
      if (ws.readyState !== WebSocket.OPEN) {
        j(new Error(`ws close ${ev.code} ${ev.reason || "(mailbox gone or rejected)"}`));
      }
    };
  });
  const welcome = await next();
  if (welcome.t !== "welcome") throw new Error("welcome");
  const n = unb64u(welcome.n, 32);
  const mac = hmac(sha256, jk, cat(te.encode("sl1/qr-join-mac"), n, mbx));
  ws.send(JSON.stringify({ t: "pair.join", id: 1, mbx: mbxB, mac: b64u(mac) }));
  const joined = await next();
  if (joined.t !== "pair.joined") throw new Error(JSON.stringify(joined));
  L("pair.joined");
  // Cellular phones often never finish ICE/TURN. Lab path: Method C join
  // authenticates the mailbox; Agent Zero then loads via same-origin proxy.
  if (stopAfterJoined) {
    try { ws.close(); } catch (_) {}
    return { home: joined.home, joined: true };
  }
  const home = unb64u(joined.home, 16);
  const envK = hkdf0(invite, cat(te.encode("sl1/qr-env"), encB(mbx), home));
  const th = sha256(cat(encB(te.encode("sl1/th/v1")), encB(te.encode("qr")), encB(mbx), encB(home), encB(new Uint8Array(0)), new Uint8Array(32), stickPub));
  const boot = hkdf(sha256, invite, th, te.encode("sl1/qr-boot"), 32);
  const ad = (dir) => cat(encB(mbx), mbx, new Uint8Array([dir]));
  const seal = (pt, dir) => {
    const nonce = crypto.getRandomValues(new Uint8Array(12));
    return cat(nonce, chacha20poly1305(envK, nonce, ad(dir)).encrypt(pt));
  };
  const open = (blob, dir) => chacha20poly1305(envK, blob.slice(0, 12), ad(dir)).decrypt(blob.slice(12));
  const pmsg = (obj) => ws.send(JSON.stringify({ t: "pmsg", body: b64u(seal(te.encode(JSON.stringify(obj)), 0x01)) }));

  const pc = new RTCPeerConnection({ iceServers: iceServers || [{ urls: "stun:stun.l.google.com:19302" }] });
  const dcP = new Promise((res) => { pc.ondatachannel = (ev) => res(ev.channel); });
  pmsg({ k: "need-offer", v: 1 });
  let offer;
  for (;;) {
    const m = await next();
    if (m.t !== "pmsg") continue;
    const obj = JSON.parse(td.decode(open(unb64u(m.body), 0x02)));
    if (obj.k === "offer") { offer = obj; break; }
  }
  await pc.setRemoteDescription({ type: "offer", sdp: offer.sdp });
  const ans = await pc.createAnswer();
  await pc.setLocalDescription(ans);
  // iOS Safari often never reaches iceGatheringState=complete with TURN — don't hang.
  await new Promise((r) => {
    if (pc.iceGatheringState === "complete") return r();
    const t = setTimeout(() => { L("ICE gather still running — sending answer (normal on cellular)"); r(); }, 8000);
    pc.onicegatheringstatechange = () => {
      if (pc.iceGatheringState === "complete") { clearTimeout(t); r(); }
    };
  });
  pmsg({ k: "answer", sdp: pc.localDescription.sdp });
  L("sent WebRTC answer");
  const dc = await dcP;
  await new Promise((r, j) => {
    const t = setTimeout(() => j(new Error("datachannel open timeout (TURN/ICE)")), 90000);
    if (dc.readyState === "open") { clearTimeout(t); r(); }
    else dc.onopen = () => { clearTimeout(t); r(); };
  });
  L("datachannel open");

  async function readIceType() {
    try {
      const stats = await pc.getStats();
      let pair = null;
      const byId = new Map();
      stats.forEach((s) => byId.set(s.id, s));
      stats.forEach((s) => {
        if (s.type === "candidate-pair" && (s.selected || s.nominated) && s.state === "succeeded") {
          pair = s;
        }
      });
      if (!pair) {
        stats.forEach((s) => {
          if (s.type === "candidate-pair" && s.state === "succeeded") pair = pair || s;
        });
      }
      if (!pair) return { iceType: "unknown", localType: null, remoteType: null };
      const local = byId.get(pair.localCandidateId);
      const remote = byId.get(pair.remoteCandidateId);
      const lt = local?.candidateType || local?.type || null;
      const rt = remote?.candidateType || remote?.type || null;
      const relay = lt === "relay" || rt === "relay";
      return {
        iceType: relay ? "relay" : "direct",
        localType: lt,
        remoteType: rt,
        protocol: local?.protocol || remote?.protocol || null,
      };
    } catch (e) {
      return { iceType: "unknown", error: String(e) };
    }
  }
  const iceInfo = await readIceType();
  L("ICE path " + iceInfo.iceType + " local=" + iceInfo.localType + " remote=" + iceInfo.remoteType);

  const sPriv = crypto.getRandomValues(new Uint8Array(32));
  const sPub = x25519.getPublicKey(sPriv);
  const ePriv = crypto.getRandomValues(new Uint8Array(32));
  const ePub = x25519.getPublicKey(ePriv);
  const prologue = qrPrologue(home, mbx, stickPub);
  const y = new Sym(prologue);
  y.mixHash(stickPub);
  y.mixHash(ePub); y.mixKey(ePub);
  y.mixKey(x25519.getSharedSecret(ePriv, stickPub));
  const cS = y.encHash(sPub);
  y.mixKey(x25519.getSharedSecret(sPriv, stickPub));
  const msg1 = cat(ePub, cS, y.encHash(new Uint8Array(0)));
  dc.send(msg1);

  const msg2 = await new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error("msg2")), 60000);
    dc.onmessage = (ev) => {
      clearTimeout(t);
      res(ev.data instanceof ArrayBuffer ? new Uint8Array(ev.data) : new Uint8Array(ev.data));
    };
  });
  const re = msg2.slice(0, 32);
  y.mixHash(re); y.mixKey(re);
  y.mixKey(x25519.getSharedSecret(ePriv, re));
  y.mixKey(x25519.getSharedSecret(sPriv, re));
  y.mixKeyAndHash(boot);
  y.decHash(msg2.slice(32));
  const [sendK, recvK] = y.split();
  const hh = y.h.slice();
  L("noise ok");

  let sendN = 0;
  const sendPt = (obj) => {
    const pt = te.encode(JSON.stringify(obj));
    const ct = aead(sendK, sendN, new Uint8Array(0), pt, true);
    const hdr = new Uint8Array(8);
    new DataView(hdr.buffer).setBigUint64(0, BigInt(sendN), true);
    sendN++;
    dc.send(cat(hdr, ct));
  };

  const recvQ = [];
  let recvWait = null;
  const decryptIncoming = (buf) => {
    const n0 = Number(new DataView(buf.buffer, buf.byteOffset, 8).getBigUint64(0, true));
    return aead(recvK, n0, new Uint8Array(0), buf.slice(8), false);
  };
  dc.onmessage = (ev) => {
    const buf = ev.data instanceof ArrayBuffer ? new Uint8Array(ev.data) : new Uint8Array(ev.data);
    try {
      const pt = decryptIncoming(buf);
      const msg = JSON.parse(td.decode(pt));
      if (recvWait) { const w = recvWait; recvWait = null; w(msg); }
      else recvQ.push(msg);
    } catch (e) {
      L("aead err " + e);
    }
  };
  const recvPt = (ms = 60000) => new Promise((res, rej) => {
    if (recvQ.length) return res(recvQ.shift());
    const t = setTimeout(() => rej(new Error("recv timeout")), ms);
    recvWait = (m) => { clearTimeout(t); res(m); };
  });

  sendPt({ t: "ready", static_pub: b64u(sPub) });
  const rI = crypto.getRandomValues(new Uint8Array(32));
  sendPt({ t: "r_i", r: b64u(rI) });
  const rRmsg = await recvPt();
  if (rRmsg.t !== "r_r") throw new Error("want r_r");
  const rR = unb64u(rRmsg.r, 32);
  const psk = derivePairPsk({ rI, rR, prior: boot, hh, th, iStatic: sPub, rStatic: stickPub, epoch: 0 });
  const kc = hkdf0(psk, te.encode("sl1/pair-confirm"));
  sendPt({ t: "confirm_i", mac: b64u(confirmMac(kc, "i", hh)) });
  const confR = await recvPt();
  if (confR.t !== "confirm_r") throw new Error("want confirm_r");
  L("pair_psk+confirm ok");

  const ready = await recvPt(120000);
  if (ready.t !== "agent_ready") throw new Error("want agent_ready got " + JSON.stringify(ready));
  L("agent_ready");

  const mux = createAppMux({ sendPt, log: L });
  // After agent_ready, all Noise PT messages go to the app-mux.
  dc.onmessage = (ev) => {
    const buf = ev.data instanceof ArrayBuffer ? new Uint8Array(ev.data) : new Uint8Array(ev.data);
    try {
      const pt = decryptIncoming(buf);
      const msg = JSON.parse(td.decode(pt));
      if (msg && typeof msg.t === "string" && (
        msg.t.startsWith("http_") || msg.t.startsWith("ws_") || msg.t === "pong" || msg.t === "ping"
      )) {
        mux.dispatch(msg);
        return;
      }
      if (recvWait) {
        const w = recvWait;
        recvWait = null;
        w(msg);
      } else recvQ.push(msg);
    } catch (e) {
      L("aead err " + e);
    }
  };

  return {
    mux,
    http: (method, path, headers, body) => mux.http(method, path, headers, body),
    installTransport: (opts) => installBrowserTransport(mux, opts),
    ws,
    dc,
    pc,
    ice: iceInfo,
    home: joined.home,
    sendPt,
  };
}
