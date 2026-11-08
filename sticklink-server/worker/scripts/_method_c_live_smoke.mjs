// Method C signalling smoke vs live Worker: hello + pair.open(qr) + pair.close.
 // Lab stick only. Prints no secrets (mailbox id ok — ephemeral).
import { createPrivateKey, randomBytes, sign } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import WebSocket from "ws";

const prov = process.argv[2] || "C:/Users/peter/sticklink-secrets/lab-stick-prov";
const base = (process.argv[3] || "https://link.stickllm.com").replace(/^http/, "ws");
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

const ws = new WebSocket(`${base}/v1/ws?dev=${encodeURIComponent(ids.dev)}`, "sticklink.1");
const next = () =>
  new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error("timeout")), 20000);
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
if (welcome.t !== "welcome") throw new Error("no welcome");
const n = unb64u(welcome.n, 32);
const body = Buffer.concat([n, unb64u(ids.dev, 16), Buffer.from([0x01]), unb64u(ids.home, 16)]);
const sig = sign(null, Buffer.concat([Buffer.from("sl1/dev-hello/v1\0"), body]), priv);
ws.send(JSON.stringify({ t: "hello", id: 1, dev: ids.dev, role: "server", home: ids.home, sig: b64u(sig) }));
const ready = await next();
if (ready.t !== "ready") throw new Error(JSON.stringify(ready));

const jk = b64u(randomBytes(32));
ws.send(JSON.stringify({ t: "pair.open", id: 2, m: "qr", jk, exp: 60 }));
const opened = await next();
if (opened.t !== "pair.ok") throw new Error(JSON.stringify(opened));

ws.send(JSON.stringify({ t: "pair.close", id: 3, mbx: opened.mbx, why: "cancel" }));
const closed = await next();
const closeOk = closed.t === "ok";

console.log(
  JSON.stringify({
    ok: true,
    method_c_pair_open: true,
    pair_close: closeOk,
    mbx_len: typeof opened.mbx === "string" ? opened.mbx.length : 0,
    home_match: ready.home === ids.home,
    base,
  }),
);
ws.close();
process.exit(0);
