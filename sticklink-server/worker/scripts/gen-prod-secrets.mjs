// Copyright (c) 2026 Nink Inc. All rights reserved.
// Generate production secrets into files (mode 0600). Prints only public
// values (kid, signing public key). Nothing is uploaded. There is no device
// master secret: devices authenticate with their own Ed25519 keys (provision.mjs).
//
//   node scripts/gen-prod-secrets.mjs --out ~/sticklink-secrets --kid prod-2026a --rg tor1
//
// Then, at deploy time (after approval):
//   wrangler secret put IP_PEPPER   < OUT/IP_PEPPER
//   wrangler secret put SIGNING_KEY < OUT/SIGNING_KEY
//   wrangler secret put RELAY_TOKENS < OUT/RELAY_TOKENS
//   relay: OUT/admit-token -> /etc/sticklink/admit-token (0600), OUT/admit-keys -> /etc/sticklink/admit-keys
import { generateKeyPairSync, randomBytes } from "node:crypto";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { args, b64u, sha256hex } from "./lib.mjs";

const a = args(process.argv.slice(2));
if (!a.out || !a.kid) {
  console.error("usage: gen-prod-secrets.mjs --out DIR --kid KID [--rg tor1]");
  process.exit(2);
}
const rg = a.rg || "tor1";
mkdirSync(a.out, { recursive: true, mode: 0o700 });
const put = (name, val) => {
  const p = join(a.out, name);
  if (existsSync(p)) throw new Error(`${p} exists; refusing to overwrite a secret`);
  writeFileSync(p, val, { mode: 0o600 });
};
const { privateKey, publicKey } = generateKeyPairSync("ed25519");
const seed = privateKey.export({ format: "jwk" }).d; // base64url 32 B seed
const pub = publicKey.export({ format: "jwk" }).x;
const relayToken = b64u(randomBytes(32));
put("IP_PEPPER", b64u(randomBytes(32)));
put("SIGNING_KEY", seed);
put("RELAY_TOKENS", JSON.stringify({ [rg]: sha256hex(relayToken) }));
put("admit-token", relayToken + "\n");
writeFileSync(join(a.out, "admit-keys"), `# Copyright (c) 2026 Nink Inc. All rights reserved.\n${a.kid} ${pub}\n`, { mode: 0o644 });
console.log(`wrote secrets to ${a.out} (0600). Public: SIGNING_KID=${a.kid} pub=${pub}`);
