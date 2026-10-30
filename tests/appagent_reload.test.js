"use strict";
// 0.5.5: after the app agent changes Node-RED (deploy or undo), the open editor tab reloads itself.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "ui", "app.js"), "utf8");
const block = src.slice(src.indexOf("const APPAGENT_TAB_IDS"), src.indexOf("async function sendToApp"));
assert.ok(block.includes("function reloadAgentAppTab"), "reload helper found");

const events = [];
const win = { dispatchEvent: (e) => events.push(e) };
class CE { constructor(type, init) { this.type = type; this.detail = init && init.detail; } }
const tabs = new Map();
const mk = (href) => ({ closed: false, nav: [], get location() { const w = this; return { set href(u) { w.nav.push(u); }, get href() { return href; } }; } });
const env = {
  appTabLink: (id) => (id === "node-red" ? { href: "http://stick.lan:8115/", target: "stickllm-node-red" } : null),
  appTabHandle: (t) => tabs.get(t) || null,
  appTabIsBlank: (w) => w.location.href === "about:blank",
};
const api = new Function("window", "CustomEvent", "location", "appTabLink", "appTabHandle", "appTabIsBlank",
  block + "\nreturn { reloadAgentAppTab };")(win, CE, { href: "http://stick.lan/" }, env.appTabLink, env.appTabHandle, env.appTabIsBlank);

// No tab open: nothing is opened, but in-page views still hear about the change.
assert.strictEqual(api.reloadAgentAppTab("nodered"), false);
assert.strictEqual(events.length, 1);
assert.strictEqual(events[0].type, "stickllm-app-changed");
assert.deepStrictEqual(events[0].detail, { app: "nodered", id: "node-red" });
// The editor tab this page opened goes back to the editor (a full load; a hash-only change would not reload).
const w = mk("http://stick.lan:8115/#flow/abc");
tabs.set("stickllm-node-red", w);
assert.strictEqual(api.reloadAgentAppTab("nodered"), true);
assert.deepStrictEqual(w.nav, ["http://stick.lan:8115/"]);
// A blank tab or an app with no link is left alone.
tabs.set("stickllm-node-red", mk("about:blank"));
assert.strictEqual(api.reloadAgentAppTab("nodered"), false);
assert.strictEqual(api.reloadAgentAppTab("onlyoffice"), false);

// Wired after a change that went through and after a successful undo, nowhere else.
const send = src.slice(src.indexOf("async function sendToApp"), src.indexOf("async function appAgentUndo"));
assert.ok(/some\(\(x\) => x\.ok\)\) \{ pend\.appUndo = app; reloadAgentAppTab\(app\); \}/.test(send));
const undo = src.slice(src.indexOf("async function appAgentUndo"), src.indexOf("async function appAgentUndo") + 1500);
assert.ok(/if \(j\.ok\) \{ m\.appUndo = ""; reloadAgentAppTab\(app\); \}/.test(undo));
assert.strictEqual((src.match(/reloadAgentAppTab\(/g) || []).length, 3);
console.log("appagent_reload ok");
