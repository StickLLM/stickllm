// Copyright (c) 2026 Nink Inc. All rights reserved.
// Provision one device (factory step). Nink 2026-10-29 (Q-S1): the DEVICE
// generates its own Ed25519 server-auth keypair (hardware TRNG on the AI KVM,
// OS CSPRNG on the stick) and hands over only the 32-byte PUBLIC key `ak`.
// This script never sees or creates a device secret. It generates the public
// device id (and, for a stick, its home id), writes them to OUT/<dev>.ids.json
// (to be written back to the device) and appends D1 INSERTs to
// OUT/provision.sql, including an audit row. Device Noise private keys and
// pairing PSKs are not involved and never reach the server.
//
//   node scripts/provision.mjs --kind stick|kvm --ak <b64u 32 B Ed25519 pub> [--cls none|stick|kvm|sub] [--days 365] [--by LABEL] --out DIR
import { randomBytes } from "node:crypto";
import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { args, b64u, sqlStr, unb64u } from "./lib.mjs";

const a = args(process.argv.slice(2));
if (!["stick", "kvm"].includes(a.kind) || !a.out || typeof a.ak !== "string") {
  console.error("usage: provision.mjs --kind stick|kvm --ak B64U_PUB [--cls C] [--days N] [--by LABEL] --out DIR");
  process.exit(2);
}
const ak = unb64u(a.ak);
if (ak.length !== 32 || b64u(ak) !== a.ak) throw new Error("--ak must be a 32-byte Ed25519 public key, unpadded base64url");
const cls = a.cls || "none";
if (!["none", "stick", "kvm", "sub"].includes(cls)) throw new Error("bad --cls");
const by = String(a.by || "factory").replace(/[^A-Za-z0-9._@-]/g, "").slice(0, 64) || "factory";
const now = Math.floor(Date.now() / 1000);
const ent = cls === "none" ? 0 : now + Number(a.days || 365) * 86400;
const dev = b64u(randomBytes(16));
const home = a.kind === "stick" ? b64u(randomBytes(16)) : null;
mkdirSync(a.out, { recursive: true, mode: 0o700 });
writeFileSync(join(a.out, `${dev}.ids.json`), JSON.stringify({ dev, home, ak: a.ak }) + "\n", { mode: 0o644 });
const rows = [
  `INSERT INTO devices(dev,kind,gen,home,status,cls,ent_until,created,ak) VALUES(${sqlStr(dev)},${sqlStr(a.kind)},0,${sqlStr(home)},'active',${sqlStr(cls)},${ent},${now},${sqlStr(a.ak)});`,
];
if (home) rows.push(`INSERT INTO homes(home,owner,created) VALUES(${sqlStr(home)},${sqlStr(dev)},${now});`);
rows.push(`INSERT INTO audit(ts,home,actor_kind,actor,op,target,result) VALUES(${now},${sqlStr(home ?? "-")},'ops',${sqlStr(by)},'dev.provision',${sqlStr(dev)},'ok');`);
appendFileSync(join(a.out, "provision.sql"), rows.join("\n") + "\n", { mode: 0o600 });
console.log(`provisioned ${a.kind} dev=${dev}${home ? " home=" + home : ""} cls=${cls}`);
