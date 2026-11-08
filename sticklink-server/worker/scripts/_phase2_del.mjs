import { createPrivateKey, sign } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import WebSocket from "ws";

const nk = process.argv[2];
if (!nk) throw new Error("usage: _phase2_del.mjs nodekey:…");
const prov = "C:/Users/peter/sticklink-secrets/lab-stick-prov";
const idsPath = readdirSync(prov).find((f) => f.endsWith(".ids.json"));
const ids = JSON.parse(readFileSync(join(prov, idsPath), "utf8"));
const seedB64 = readFileSync(join(prov, "device-auth-seed"), "utf8").trim();
const priv = createPrivateKey({ key: { kty: "OKP", crv: "Ed25519", d: seedB64, x: ids.ak }, format: "jwk" });
const unb64u = (s, n) => {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const b = Buffer.from(s.replace(/-/g, "+").replace(/_/g, "/") + pad, "base64");
  if (n != null && b.length !== n) throw new Error("len");
  return b;
};
const b64u = (b) => Buffer.from(b).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const ws = new WebSocket(`wss://link.stickllm.com/v1/ws?dev=${encodeURIComponent(ids.dev)}`, "sticklink.1");
const next = () =>
  new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error("timeout")), 15000);
    ws.once("message", (d) => {
      clearTimeout(t);
      res(JSON.parse(String(d)));
    });
  });
await new Promise((r, j) => {
  ws.once("open", r);
  ws.once("error", j);
});
const welcome = await next();
const n = unb64u(welcome.n, 32);
const body = Buffer.concat([n, unb64u(ids.dev, 16), Buffer.from([0x01]), unb64u(ids.home, 16)]);
const sig = sign(null, Buffer.concat([Buffer.from("sl1/dev-hello/v1\0"), body]), priv);
ws.send(JSON.stringify({ t: "hello", id: 1, dev: ids.dev, role: "server", home: ids.home, sig: b64u(sig) }));
await next();
ws.send(JSON.stringify({ t: "relay.del", id: 6, nk }));
const del = await next();
console.log(JSON.stringify({ del: del.t, id: del.id }));
ws.close();
