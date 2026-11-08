// Copyright (c) 2026 Nink Inc. All rights reserved.
// HMAC-SHA256, HKDF-SHA256, Ed25519 signing. WebCrypto only.
import { b64u, concat, hex, u32be, unb64u, utf8 } from "./b64";
import { ipBucket } from "./ipbucket";

export async function hmac(key: Uint8Array, msg: Uint8Array): Promise<Uint8Array> {
  const k = await crypto.subtle.importKey("raw", key, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", k, msg));
}

export async function hmacVerify(key: Uint8Array, msg: Uint8Array, mac: Uint8Array): Promise<boolean> {
  const k = await crypto.subtle.importKey("raw", key, { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
  return crypto.subtle.verify("HMAC", k, mac, msg); // constant-time compare
}

export async function sha256(msg: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", msg));
}

/** HKDF-SHA256 with empty salt, as in PAIRING-SPEC (`HKDF(ikm, info)`). */
export async function hkdf(ikm: Uint8Array, info: string, len = 32): Promise<Uint8Array> {
  const k = await crypto.subtle.importKey("raw", ikm, "HKDF", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "HKDF", hash: "SHA-256", salt: new Uint8Array(0), info: utf8(info) },
    k,
    len * 8,
  );
  return new Uint8Array(bits);
}

// ---- device server-auth (Nink 2026-10-29, Q-S1) ----------------------------
// Each device generates its own random Ed25519 server-auth keypair on the device
// (separate from its Noise X25519 static key). The server stores only the public
// key `ak` in D1 and checks a signature over the fresh server nonce, so nothing in
// D1, Worker secrets or a TLS terminator can be replayed as a device credential.
// Device Noise private keys and pairing PSKs never reach the server.
export const ROLE_SERVER = 1;
export const ROLE_CLIENT = 2;
export const DOM_DEV_HELLO = "sl1/dev-hello/v1";
export const DOM_DEV_ROTATE = "sl1/dev-rotate/v1";

/** hello signed body (fixed length, 65 B): n(32) || dev(16) || role(1) || home(16; zeros for a client). */
export function helloBody(n: Uint8Array, dev: Uint8Array, role: number, home: Uint8Array | null): Uint8Array {
  return concat(n, dev, new Uint8Array([role]), home ?? new Uint8Array(16));
}

/** auth.rotate proof of possession body (112 B): n(32) || dev(16) || new_ak(32) || old_ak(32). */
export function rotateBody(n: Uint8Array, dev: Uint8Array, newAk: Uint8Array, oldAk: Uint8Array): Uint8Array {
  return concat(n, dev, newAk, oldAk);
}

export function joinInput(n: Uint8Array, home: Uint8Array, slot: Uint8Array): Uint8Array {
  return concat(utf8("sl1/join"), n, home, slot);
}

export function qrJoinInput(n: Uint8Array, mbx: Uint8Array): Uint8Array {
  return concat(utf8("sl1/qr-join-mac"), n, mbx);
}

// ---- Ed25519 -----------------------------------------------------------------
const PKCS8_ED25519_PREFIX = Uint8Array.from([
  0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x04, 0x22, 0x04, 0x20,
]);

export interface Signer {
  kid: string;
  pub: Uint8Array;
  sign(domain: string, body: Uint8Array): Promise<Uint8Array>;
}

const signerCache = new Map<string, Promise<Signer>>();

/** SIGNING_KEY is a 32-byte Ed25519 seed, base64url. */
export function getSigner(seedB64: string, kid: string): Promise<Signer> {
  const ck = kid + ":" + seedB64;
  let p = signerCache.get(ck);
  if (!p) {
    p = (async () => {
      const seed = unb64u(seedB64, 32);
      if (!seed) throw new Error("SIGNING_KEY must be a 32-byte base64url seed");
      const sk = await crypto.subtle.importKey("pkcs8", concat(PKCS8_ED25519_PREFIX, seed), { name: "Ed25519" }, true, ["sign"]);
      const jwk = (await crypto.subtle.exportKey("jwk", sk)) as JsonWebKey;
      const pub = unb64u(jwk.x)!;
      return {
        kid,
        pub,
        async sign(domain: string, body: Uint8Array) {
          return new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, sk, signedInput(domain, body)));
        },
      };
    })();
    signerCache.set(ck, p);
  }
  return p;
}

/** Every signature covers: domain || 0x00 || body. */
export function signedInput(domain: string, body: Uint8Array): Uint8Array {
  return concat(utf8(domain), new Uint8Array([0]), body);
}

export async function ed25519Verify(pub: Uint8Array, domain: string, body: Uint8Array, sig: Uint8Array): Promise<boolean> {
  if (pub.length !== 32 || sig.length !== 64) return false;
  try {
    const k = await crypto.subtle.importKey("raw", pub, { name: "Ed25519" }, false, ["verify"]);
    return await crypto.subtle.verify({ name: "Ed25519" }, k, sig, signedInput(domain, body));
  } catch {
    return false; // malformed key: same answer as a bad signature
  }
}

export const DOM_ALLOWLIST = "sl1/allowlist/v1";
export const DOM_PERMIT = "sl1/permit/v1";
export const DOM_REVOKED = "sl1/revoked/v1";

/** Signed envelope: body is the exact JSON bytes that were signed, base64url. */
export async function signEnvelope(s: Signer, domain: string, obj: unknown): Promise<{ kid: string; body: string; sig: string }> {
  const body = utf8(JSON.stringify(obj));
  return { kid: s.kid, body: b64u(body), sig: b64u(await s.sign(domain, body)) };
}

/** Keyed, non-reversible bucket name for an IP address (never stored raw). */
/** Rate-limit key: HMAC(pepper, bucket(ip)); IPv6 is bucketed by /64. The raw IP is never stored. */
export async function ipKey(pepper: string, ip: string): Promise<string> {
  return hex((await hmac(utf8(pepper), utf8("sl1/ip|" + ipBucket(ip)))).slice(0, 16));
}

export function ctEqualStr(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}
