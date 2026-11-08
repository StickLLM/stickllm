/* Lab-only Noise_IKpsk2_25519_ChaChaPoly_SHA256 (browser). Matches sticklink noise.py / ikpsk2-v2. */
(function (global) {
  const TAG = 16;
  async function sha256(buf) {
    return new Uint8Array(await crypto.subtle.digest("SHA-256", buf));
  }
  async function hmac(key, data) {
    const k = await crypto.subtle.importKey("raw", key, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    return new Uint8Array(await crypto.subtle.sign("HMAC", k, data));
  }
  async function hkdfNoise(ck, ikm, n) {
    const t = await hmac(ck, ikm);
    const o1 = await hmac(t, new Uint8Array([1]));
    const o2 = await hmac(t, cat(o1, new Uint8Array([2])));
    if (n === 2) return [o1, o2];
    const o3 = await hmac(t, cat(o2, new Uint8Array([3])));
    return [o1, o2, o3];
  }
  function cat(...parts) {
    const n = parts.reduce((a, p) => a + p.length, 0);
    const out = new Uint8Array(n);
    let o = 0;
    for (const p of parts) { out.set(p, o); o += p.length; }
    return out;
  }
  function nonce(n) {
    const b = new Uint8Array(12);
    new DataView(b.buffer).setBigUint64(4, BigInt(n), true);
    return b;
  }
  async function aeadEnc(k, n, ad, pt) {
    const key = await crypto.subtle.importKey("raw", k, { name: "ChaCha20-Poly1305" }, false, ["encrypt"]);
    return new Uint8Array(await crypto.subtle.encrypt({ name: "ChaCha20-Poly1305", iv: nonce(n), additionalData: ad }, key, pt));
  }
  async function aeadDec(k, n, ad, ct) {
    const key = await crypto.subtle.importKey("raw", k, { name: "ChaCha20-Poly1305" }, false, ["decrypt"]);
    return new Uint8Array(await crypto.subtle.decrypt({ name: "ChaCha20-Poly1305", iv: nonce(n), additionalData: ad }, key, ct));
  }
  async function x25519(priv, pub) {
    // WebCrypto X25519 (Chrome 133+ / recent Chromium)
    const pk = await crypto.subtle.importKey("raw", priv, { name: "X25519" }, false, ["deriveBits"]);
    const peer = await crypto.subtle.importKey("raw", pub, { name: "X25519" }, false, []);
    const bits = await crypto.subtle.deriveBits({ name: "X25519", public: peer }, pk, 256);
    const out = new Uint8Array(bits);
    if (out.every((b) => b === 0)) throw new Error("low-order");
    return out;
  }
  async function x25519Pub(priv) {
    const pk = await crypto.subtle.importKey("raw", priv, { name: "X25519" }, true, ["deriveBits"]);
    const jwk = await crypto.subtle.exportKey("jwk", pk);
    const raw = Uint8Array.from(atob(jwk.x.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
    // jwk.x is already the public; for X25519 import of private we need generate from seed via Subtle
    // Chromium: import PKCS8. Fallback: use @noble if needed — try derive from known API.
    return raw;
  }
  // Prefer @noble path injected by harness if WebCrypto private->public is awkward.
  class Sym {
    constructor() { this.h = null; this.ck = null; this.k = null; this.n = 0; }
    async init(prologue) {
      const name = new TextEncoder().encode("Noise_IKpsk2_25519_ChaChaPoly_SHA256");
      this.h = name.length > 32 ? await sha256(name) : cat(name, new Uint8Array(32 - name.length));
      this.ck = this.h.slice();
      await this.mixHash(prologue);
    }
    async mixHash(d) { this.h = await sha256(cat(this.h, d)); }
    async mixKey(ikm) { const [ck, k] = await hkdfNoise(this.ck, ikm, 2); this.ck = ck; this.k = k; this.n = 0; }
    async mixKeyAndHash(ikm) {
      const [ck, t, k] = await hkdfNoise(this.ck, ikm, 3);
      this.ck = ck; await this.mixHash(t); this.k = k; this.n = 0;
    }
    async encHash(pt) {
      let ct;
      if (!this.k) ct = pt;
      else { ct = await aeadEnc(this.k, this.n++, this.h, pt); }
      await this.mixHash(ct);
      return ct;
    }
    async decHash(ct) {
      let pt;
      if (!this.k) pt = ct;
      else { pt = await aeadDec(this.k, this.n++, this.h, ct); }
      await this.mixHash(ct);
      return pt;
    }
    async split() { return hkdfNoise(this.ck, new Uint8Array(0), 2); }
  }
  class Session {
    constructor(sendK, recvK, hh, remote) {
      this.sendK = sendK; this.recvK = recvK; this.hh = hh; this.remote = remote;
      this.sendN = 0; this.maxRecv = -1;
    }
    async encrypt(pt) {
      const n = this.sendN++;
      return { n, ct: await aeadEnc(this.sendK, n, new Uint8Array(0), pt) };
    }
    async decrypt(n, ct) {
      return aeadDec(this.recvK, n, new Uint8Array(0), ct);
    }
  }
  global.StickNoise = {
    cat, sha256, hmac, aeadEnc, aeadDec, x25519, Session, Sym,
    async initiatorMsg1(sPriv, sPub, rsPub, psk, prologue, ePriv, ePub, dh) {
      const y = new Sym(); await y.init(prologue); await y.mixHash(rsPub);
      await y.mixHash(ePub); await y.mixKey(ePub);
      await y.mixKey(await dh(ePriv, rsPub));
      const cS = await y.encHash(sPub);
      await y.mixKey(await dh(sPriv, rsPub));
      const msg1 = cat(ePub, cS, await y.encHash(new Uint8Array(0)));
      return { y, msg1, psk };
    },
    async initiatorMsg2(state, msg2, dh, ePriv, sPriv, psk) {
      const y = state.y;
      const re = msg2.slice(0, 32);
      await y.mixHash(re); await y.mixKey(re);
      await y.mixKey(await dh(ePriv, re));
      await y.mixKey(await dh(sPriv, re));
      await y.mixKeyAndHash(psk);
      await y.decHash(msg2.slice(32));
      const [k1, k2] = await y.split();
      return new Session(k1, k2, y.h, null);
    },
  };
})(globalThis);
