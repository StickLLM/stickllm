// Copyright (c) 2026 Nink Inc. All rights reserved.
// Operator device actions (Nink 2026-10-29, Q-S1/Q-S12). Emits SQL to stdout
// for review; it does not touch any database. Every action carries an audit
// row (actor_kind 'ops'). Apply after review with
//   wrangler d1 execute sticklink --file OUT.sql   (production: only with approval)
//
//   node scripts/devctl.mjs disable --dev DEV --by LABEL [--home HOME]
//   node scripts/devctl.mjs enable  --dev DEV --by LABEL [--home HOME]
//   node scripts/devctl.mjs setak   --dev DEV --ak B64U_PUB --by LABEL [--home HOME]   (lost-key re-enrolment)
//
// disable: the device can no longer complete hello (err auth, close 4401) and
// gets no new relay permits; its existing DO sockets end at their next
// re-auth. setak replaces the auth public key and bumps gen.
import { args, b64u, sqlStr, unb64u } from "./lib.mjs";

const [cmd, ...rest] = process.argv.slice(2);
const a = args(rest);
const ok16 = (s) => typeof s === "string" && unb64u(s).length === 16 && b64u(unb64u(s)) === s;
if (!["disable", "enable", "setak"].includes(cmd) || !ok16(a.dev) || typeof a.by !== "string" || (a.home !== undefined && !ok16(a.home))) {
  console.error("usage: devctl.mjs disable|enable|setak --dev DEV --by LABEL [--home HOME] [--ak B64U_PUB]");
  process.exit(2);
}
const by = a.by.replace(/[^A-Za-z0-9._@-]/g, "").slice(0, 64);
const now = Math.floor(Date.now() / 1000);
const home = a.home ?? "-";
const out = ["-- Copyright (c) 2026 Nink Inc. All rights reserved.", `-- devctl ${cmd} ${a.dev} by ${by}`];
if (cmd === "setak") {
  const ak = typeof a.ak === "string" ? unb64u(a.ak) : new Uint8Array();
  if (ak.length !== 32 || b64u(ak) !== a.ak) throw new Error("--ak must be a 32-byte Ed25519 public key, unpadded base64url");
  out.push(`UPDATE devices SET ak=${sqlStr(a.ak)}, gen=gen+1 WHERE dev=${sqlStr(a.dev)};`);
  out.push(`INSERT INTO audit(ts,home,actor_kind,actor,op,target,result) VALUES(${now},${sqlStr(home)},'ops',${sqlStr(by)},'dev.setak',${sqlStr(a.dev)},'ok');`);
} else {
  const st = cmd === "disable" ? "disabled" : "active";
  out.push(`UPDATE devices SET status='${st}' WHERE dev=${sqlStr(a.dev)};`);
  if (cmd === "disable") {
    // Withdraw its relay permits through the allowlist log so sidecars drop them (new admissions denied;
    // already-open relay connections may persist, Q-R6).
    out.push(`INSERT INTO al_log(rg,op,nk,ts) SELECT rg,'del',nk,${now} FROM permits WHERE holder=${sqlStr(a.dev)};`);
    out.push(`DELETE FROM permits WHERE holder=${sqlStr(a.dev)};`);
  }
  out.push(`INSERT INTO audit(ts,home,actor_kind,actor,op,target,result) VALUES(${now},${sqlStr(home)},'ops',${sqlStr(by)},'dev.${cmd}',${sqlStr(a.dev)},'ok');`);
}
console.log(out.join("\n"));
