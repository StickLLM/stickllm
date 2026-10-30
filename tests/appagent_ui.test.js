"use strict";
// App agent chat wiring in ui/app.js: routing to /appagent/act and the reply text.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "ui", "app.js"), "utf8");
const block = src.slice(src.indexOf("const APPAGENT_NAMES"), src.indexOf("function setAppTarget"));
assert.ok(block.length > 200, "app agent block found");
const picker = { hidden: false, value: "" };
const $ = (sel) => (sel === "#appTarget" ? picker : null);
const api = new Function("$", block + "\nreturn { appAgentRoute, appAgentReply, setApps: (a) => { appAgentApps = a; } };")($);
api.setApps(["onlyoffice", "nodered"]);

assert.strictEqual(api.appAgentRoute("hello"), null);
assert.deepStrictEqual(api.appAgentRoute("@office draw a big yellow box"), { app: "onlyoffice", text: "draw a big yellow box" });
assert.deepStrictEqual(api.appAgentRoute("@Node-RED: add an inject node"), { app: "nodered", text: "add an inject node" });
assert.strictEqual(api.appAgentRoute("@office"), null);
picker.value = "onlyoffice";
assert.deepStrictEqual(api.appAgentRoute("  make it bigger "), { app: "onlyoffice", text: "make it bigger" });
assert.strictEqual(api.appAgentRoute("   "), null);
picker.hidden = true;
assert.strictEqual(api.appAgentRoute("make it bigger"), null);
api.setApps(["onlyoffice"]);
assert.strictEqual(api.appAgentRoute("@nodered add a node"), null);

const reply = api.appAgentReply("onlyoffice", {
  understanding: "Add a big yellow rectangle.",
  results: [{ cmd: "add rect", ok: true, out: "" }, { cmd: "move x", ok: false, out: "no such shape" }],
});
assert.ok(reply.startsWith("**ONLYOFFICE slides:** Add a big yellow rectangle."));
assert.ok(reply.includes("✓ `add rect`") && reply.includes("✗ `move x` — no such shape"));
assert.ok(api.appAgentReply("nodered", { understanding: "", results: [], plan_err: "bad json" }).includes("No change: bad json"));

assert.ok(src.includes('fetch("/appagent/act"') && src.includes('fetch("/appagent/undo"'));
assert.ok(src.includes("data-appundo"));
const html = fs.readFileSync(path.join(__dirname, "..", "ui", "index.html"), "utf8");
assert.ok(/<select class="appTarget" id="appTarget" hidden/.test(html));
const docs = fs.readFileSync(path.join(__dirname, "..", "ui", "apps", "docs", "docs.js"), "utf8");
assert.ok(docs.includes('new BroadcastChannel("stickllm-appagent")') && src.includes('new BroadcastChannel("stickllm-appagent")'));
console.log("appagent_ui ok");
