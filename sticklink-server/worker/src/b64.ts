// Copyright (c) 2026 Nink Inc. All rights reserved.
// base64url (no padding) and byte helpers. WebCrypto/stdlib only.

export function b64u(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

const B64U_RE = /^[A-Za-z0-9_-]*$/;

/** Decode base64url without padding. Returns null on any malformed input. */
export function unb64u(s: unknown, expectLen?: number): Uint8Array | null {
  if (typeof s !== "string" || !B64U_RE.test(s) || s.length % 4 === 1) return null;
  let t = s.replace(/-/g, "+").replace(/_/g, "/");
  while (t.length % 4) t += "=";
  let bin: string;
  try {
    bin = atob(t);
  } catch {
    return null;
  }
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  if (expectLen !== undefined && out.length !== expectLen) return null;
  // Reject non-canonical encodings so every value has exactly one wire form.
  if (b64u(out) !== s) return null;
  return out;
}

export function hex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function unhex(s: string): Uint8Array {
  if (!/^([0-9a-f]{2})*$/.test(s)) throw new Error("bad hex");
  const out = new Uint8Array(s.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(s.slice(i * 2, i * 2 + 2), 16);
  return out;
}

export const utf8 = (s: string): Uint8Array => new TextEncoder().encode(s);

export function concat(...parts: Uint8Array[]): Uint8Array {
  let n = 0;
  for (const p of parts) n += p.length;
  const out = new Uint8Array(n);
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}

export function u32be(n: number): Uint8Array {
  const b = new Uint8Array(4);
  new DataView(b.buffer).setUint32(0, n >>> 0);
  return b;
}

export function randomBytes(n: number): Uint8Array {
  const b = new Uint8Array(n);
  crypto.getRandomValues(b);
  return b;
}

/** Uniform random integer in [0, n). */
export function randomInt(n: number): number {
  const lim = Math.floor(0x100000000 / n) * n;
  const b = new Uint32Array(1);
  for (;;) {
    crypto.getRandomValues(b);
    if (b[0] < lim) return b[0] % n;
  }
}
