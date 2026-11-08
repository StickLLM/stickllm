// Copyright (c) 2026 Nink Inc. All rights reserved.
// Shared helpers for the sticklink scripts (Node >= 20, no dependencies).
import { createHash, createHmac, createPrivateKey, createPublicKey, sign as edSign } from "node:crypto";

export const b64u = (b) => Buffer.from(b).toString("base64url");
export const unb64u = (s) => new Uint8Array(Buffer.from(s, "base64url"));
export const u32be = (n) => { const b = Buffer.alloc(4); b.writeUInt32BE(n); return b; };
export const hmac = (k, ...parts) => new Uint8Array(createHmac("sha256", k).update(Buffer.concat(parts.map((p) => Buffer.from(p)))).digest());
export const sha256hex = (s) => createHash("sha256").update(s).digest("hex");
// Ed25519 from a 32-byte seed (RFC 8032) via PKCS#8; node:crypto only.
const PKCS8_ED25519 = Buffer.from("302e020100300506032b657004220420", "hex");
export const edKey = (seed) => createPrivateKey({ key: Buffer.concat([PKCS8_ED25519, Buffer.from(seed)]), format: "der", type: "pkcs8" });
export const edPub = (seed) => new Uint8Array(createPublicKey(edKey(seed)).export({ format: "der", type: "spki" }).subarray(-32));
export const edSignDom = (seed, domain, body) => new Uint8Array(edSign(null, Buffer.concat([Buffer.from(domain), Buffer.from([0]), Buffer.from(body)]), edKey(seed)));
// Device server-auth (Q-S1, Nink 2026-10-29): Ed25519 over the server nonce.
export const ROLE_SERVER = 1, ROLE_CLIENT = 2;
export const helloBody = (n, dev, role, home) => Buffer.concat([n, dev, Buffer.from([role]), home ?? Buffer.alloc(16)]);
export const helloSig = (seed, n, dev, role, home) => edSignDom(seed, "sl1/dev-hello/v1", helloBody(n, dev, role, home));
export const rotatePop = (newSeed, n, dev, newAk, oldAk) => edSignDom(newSeed, "sl1/dev-rotate/v1", Buffer.concat([n, dev, newAk, oldAk]));
export const joinInput = (n, home, slot) => Buffer.concat([Buffer.from("sl1/join"), n, home, slot]);
export const qrJoinInput = (n, mbx) => Buffer.concat([Buffer.from("sl1/qr-join-mac"), n, mbx]);
export const sqlStr = (s) => (s === null ? "NULL" : "'" + String(s).replace(/'/g, "''") + "'");
export function args(argv) {
  const o = {};
  for (let i = 0; i < argv.length; i++) if (argv[i].startsWith("--")) o[argv[i].slice(2)] = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : true;
  return o;
}
