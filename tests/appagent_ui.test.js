"use strict";
// App agent chat wiring in ui/app.js (0.5.6): no picker. Routing is "in <App>,"
// or @app, a picked app, the last-used app window, then a keyword router over
// installed apps only; plus the reply text.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "ui", "app.js"), "utf8");
const block = src.slice(src.indexOf("const APPAGENT_NAMES"), src.indexOf("function appAgentRecent"));
assert.ok(block.length > 200, "app agent block found");
const api = new Function(block + `
return { appAgentRoute, appAgentReply, appAgentWins,
  setApps: (a) => { appAgentApps = a; }, pin: (a) => { appAgentPinned = a; }, skip: (v) => { appAgentSkipOnce = v; } };`)();
api.setApps(["onlyoffice", "nodered"]);

assert.strictEqual(api.appAgentRoute("hello"), null);
assert.deepStrictEqual(api.appAgentRoute("@office draw a big yellow box"), { app: "onlyoffice", text: "draw a big yellow box", why: "named" });
assert.deepStrictEqual(api.appAgentRoute("@Node-RED: add an inject node"), { app: "nodered", text: "add an inject node", why: "named" });
assert.deepStrictEqual(api.appAgentRoute("in Node-RED, add an inject node"), { app: "nodered", text: "add an inject node", why: "named" });
assert.deepStrictEqual(api.appAgentRoute("In the slides app: make the title red"), { app: "onlyoffice", text: "make the title red", why: "named" });
assert.strictEqual(api.appAgentRoute("@office"), null);
assert.strictEqual(api.appAgentRoute("in notepad, write hi"), null, "Notepad is not installed here");
assert.strictEqual(api.appAgentRoute("   "), null);
// Keyword router: exactly one installed app matches.
assert.deepStrictEqual(api.appAgentRoute("add a rectangle"), { app: "onlyoffice", text: "add a rectangle", why: "matched" });
assert.deepStrictEqual(api.appAgentRoute("wire the inject node to a debug node"), { app: "nodered", text: "wire the inject node to a debug node", why: "matched" });
assert.strictEqual(api.appAgentRoute("what is the capital of France"), null);
// The last-used window wins; old focus (over 2 min) does not count.
const now = Date.now();
api.appAgentWins.set("nodered:", { id: "nodered", inst: "", focusT: now - 1000, seen: now });
assert.deepStrictEqual(api.appAgentRoute("make it bigger", now), { app: "nodered", text: "make it bigger", why: "last used" });
assert.strictEqual(api.appAgentRoute("what time is it", now + 5 * 60 * 1000), null);
api.skip(true);
assert.strictEqual(api.appAgentRoute("make it bigger", now), null, "✕ sends one message to chat");
assert.deepStrictEqual(api.appAgentRoute("in office, add a slide", now), { app: "onlyoffice", text: "add a slide", why: "named" });
api.skip(false);
api.pin("onlyoffice");
assert.deepStrictEqual(api.appAgentRoute("  make it bigger ", now), { app: "onlyoffice", text: "make it bigger", why: "picked" });
api.pin("");
api.appAgentWins.clear();
// Browser apps are only routed by keyword when a window of them is open.
api.setApps(["notepad", "calculator"]);
assert.strictEqual(api.appAgentRoute("open the calculator and add 2 and 2"), null);
api.appAgentWins.set("calculator:a", { id: "calculator", inst: "a", focusT: 0, seen: now });
assert.strictEqual(api.appAgentRoute("on the calculator add 2 and 2").app, "calculator");
assert.deepStrictEqual(api.appAgentRoute("in calc, 2+2"), { app: "calculator", text: "2+2", why: "named" });
api.setApps(["onlyoffice"]);
assert.strictEqual(api.appAgentRoute("@nodered add a node"), null);

const reply = api.appAgentReply("onlyoffice", {
  understanding: "Add a big yellow rectangle.",
  results: [{ cmd: "add rect", ok: true, out: "" }, { cmd: "move x", ok: false, out: "no such shape" }],
});
assert.ok(reply.startsWith("**ONLYOFFICE slides:** Add a big yellow rectangle."));
assert.ok(reply.includes("✓ `add rect`") && reply.includes("✗ `move x` — no such shape"));
assert.ok(api.appAgentReply("nodered", { understanding: "", results: [], plan_err: "bad json" }).includes("No change: bad json"));
assert.ok(api.appAgentReply("notepad", { error: "no_model", message: "Load a model first." }).includes("Load a model first."));

assert.ok(src.includes('fetch("/appagent/act"') && src.includes('fetch("/appagent/undo"'));
assert.ok(src.includes("data-appundo"));
assert.ok(src.includes('control(appAgentOn ? "appagent_unload" : "appagent_load"'));
const html = fs.readFileSync(path.join(__dirname, "..", "ui", "index.html"), "utf8");
assert.ok(!/id="appTarget"/.test(html), "no app picker list");
assert.ok(/id="appAgentToggle"/.test(html) && /id="appAgentSearch"/.test(html) && /id="appAgentRecent"/.test(html));
const docs = fs.readFileSync(path.join(__dirname, "..", "ui", "apps", "docs", "docs.js"), "utf8");
assert.ok(docs.includes('new BroadcastChannel("stickllm-appagent")') && src.includes('new BroadcastChannel("stickllm-appagent")'));
const bridge = fs.readFileSync(path.join(__dirname, "..", "ui", "apps", "stickllm-bridge.js"), "utf8");
assert.ok(bridge.includes('"stickllm-appbridge"') && src.includes('new BroadcastChannel("stickllm-appbridge")'));
console.log("appagent_ui ok");
