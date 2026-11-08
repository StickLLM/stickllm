// Phase 1 smoke only — lab stick hello/ready against deployed Worker. No secrets printed.
import { createPrivateKey, sign } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import WebSocket from "ws";

const prov = process.argv[2] || "C:/Users/peter/sticklink-secrets/lab-stick-prov";
const base = (process.argv[3] || "https://link.stickllm.com").replace(/^http/, "ws");
const idsPath = readdirSync(prov).find((f) => f.endsWith(".ids.json"));
const ids = JSON.parse(readFileSync(join(prov, idsPath), "utf8"));
const seedB64 = readFileSync(join(prov, "device-auth-seed"), "utf8").trim();
const seed = Buffer.from(seedB64.replace(/-/g, "+").replace(/_/g, "/"), "base64");
const priv = createPrivateKey({ key: { kty: "OKP", crv: "Ed25519", d: seedB64, x: ids.ak }, format: "jwk" });

function unb64u(s, n) {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const b = Buffer.from(s.replace(/-/g, "+").replace(/_/g, "/") + pad, "base64");
  if (n != null && b.length !== n) throw new Error("len");
  return b;
}
function b64u(b) {
  return Buffer.from(b).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

const url = `${base}/v1/ws?dev=${encodeURIComponent(ids.dev)}`;
const ws = new WebSocket(url, "sticklink.1");
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
if (welcome.t !== "welcome") throw new Error(JSON.stringify(welcome));
const n = unb64u(welcome.n, 32);
const dev = unb64u(ids.dev, 16);
const home = unb64u(ids.home, 16);
const body = Buffer.concat([n, dev, Buffer.from([0x01]), home]);
const msg = Buffer.concat([Buffer.from("sl1/dev-hello/v1\0"), body]);
const sig = sign(null, msg, priv);
ws.send(JSON.stringify({ t: "hello", id: 1, dev: ids.dev, role: "server", home: ids.home, sig: b64u(sig) }));
const ready = await next();
if (ready.t !== "ready") throw new Error(JSON.stringify(ready));
console.log(JSON.stringify({ ok: true, ready_home: ready.home, home_match: ready.home === ids.home }));
ws.close();
process.exit(0);
